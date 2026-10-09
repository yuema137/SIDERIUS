# agent/schemas/implementor.py
"""
Input and output schemas for ml_model_implementor.

This node consumes a ProposalOutput and produces a validated plugin file
and test file below its configured workspace. It does not register the plugin
itself — that is verified by code_validator_agent.
"""

from __future__ import annotations

import os
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.schemas.hyperparam_tuning import ExpertAdviceInput, TaskCompositionRef
from agent.schemas.model_io_contract import ModelIOContract
from agent.schemas.model_probe import ModelProbeContext
from agent.schemas.output_types import OutputTypeName
from agent.schemas.proposal import CustomLossSpec
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.task_config import ForwardContract
from core.capability_registry import CapabilityContractSnapshot, CapabilityMetadata
from core.hardware_context import HardwareContext

# Fields the implementor is NEVER allowed to adjust. These are owned by the
# proposer (dataset-level, global, knowable at proposal time). A violation
# must retry the proposer, not the implementor.
# See docs/improving_validation_awareness.md §2.1 + §2.4 (Phase B.1).
_FORBIDDEN_ADJUSTMENT_FIELDS: frozenset[str] = frozenset({"segmentation_size"})

# Maximum allowed relative delta for numeric adjustments. Per locked decision
# in docs/improving_validation_awareness.md §5.2 ("±20% adjustment threshold
# accepted as the default"). Applied universally to int and float fields —
# distinguishing "continuous" from "discrete numeric with constraint" from
# type alone is unreliable (both are typically int). Revisit if legitimate
# multiple_of snaps fire this too often.
_MAX_ADJUSTMENT_DELTA: float = 0.20


class ConfigAdjustment(BaseModel):
    """
    One field-level adjustment the implementor made to reconcile the proposer's
    baseline_config['model_config'] with its own pydantic schema.

    Recorded in ``ImplementorOutput.baseline_config_adjustments`` keyed by
    field name, so downstream consumers (tuner, interpreter, reflector) can
    see exactly what the LLM changed before training was attempted.

    Enforces the §2.4 adjustment policy on a single entry:
      - numeric (int/float, non-bool): ``|new - old| / |old| <= 0.20``
      - bool / non-numeric: REJECTED — must relax the schema instead

    The forbidden-field check (segmentation_size and friends) lives at the
    ``ImplementorOutput`` level because it depends on the dict key, which
    is not available inside this model.

    See docs/improving_validation_awareness.md Phase B.1.
    """

    original_value: Any = Field(
        description="The value originally proposed by the proposer (before the adjustment).",
    )
    adjusted_value: Any = Field(
        description="The value the implementor is using instead, chosen to satisfy its own schema constraint.",
    )
    reason: str = Field(
        min_length=1,
        description="Why this adjustment was made. "
        "E.g. '5 -> 4 to satisfy multiple_of=2 constraint on refiner_kernel_size'. "
        "Must be non-empty so the audit trail is human-readable.",
    )

    @model_validator(mode="after")
    def _enforce_delta_policy(self):
        orig = self.original_value
        new = self.adjusted_value

        # Bool is categorical (§2.4) — not adjustable. Must relax the schema.
        # Check bool BEFORE the (int, float) check since bool is a subclass of int.
        if isinstance(orig, bool) or isinstance(new, bool):
            raise ValueError(
                "ConfigAdjustment does not support boolean fields. "
                "Booleans are categorical — relax the schema constraint instead "
                "of adjusting the baseline value."
            )

        # Only numeric adjustments are supported. Strings/lists/dicts are categorical.
        if not isinstance(orig, (int, float)) or not isinstance(new, (int, float)):
            raise ValueError(
                f"ConfigAdjustment only supports numeric (int/float) adjustments; "
                f"got original={type(orig).__name__}, adjusted={type(new).__name__}. "
                f"For string/list/dict fields, relax the schema constraint instead."
            )

        # Degenerate: original is zero. Any non-zero adjustment is an unbounded
        # relative delta; require equality to keep the audit trail meaningful.
        if orig == 0:
            if new != 0:
                raise ValueError(
                    f"adjusted_value={new} but original_value=0 — relative delta "
                    f"is undefined. Either the field should be non-zero in the "
                    f"baseline, or no adjustment should be recorded."
                )
            return self

        rel = abs(new - orig) / abs(orig)
        if rel > _MAX_ADJUSTMENT_DELTA:
            raise ValueError(
                f"adjusted_value={new} deviates {rel:.1%} from original_value={orig}, "
                f"exceeding the ±{int(_MAX_ADJUSTMENT_DELTA * 100)}% adjustment limit. "
                f"A change this large is a structural rewrite, not a reconciliation — "
                f"relax the schema constraint instead."
            )
        return self


class LossProvenance(BaseModel):
    """Full audit trail for a single loss plugin use.

    Present whenever ``baseline_config['loss_config']['loss_type'] == "custom"``.
    ``None`` when the iteration is using a built-in loss type (focal, focal_cw,
    ce, smooth_l1).

    Two actions are distinguished so the interpreter and reflector can tell
    which iteration is responsible for the plugin's existence (for credit
    assignment) vs which iteration merely reused it:

    - ``action="generated"``: the implementor wrote the plugin file *this*
      iteration after a fresh LLM call. ``source_iteration`` equals the
      current iteration's ``run_name``.
    - ``action="reused"``: the plugin already existed in the registry; the
      implementor made no LLM call for the loss this iteration.
      ``source_iteration`` equals the ``run_name`` from the registry entry —
      i.e. the iteration that originally created it.

    See ``docs/design/enable_loss_inventory.md`` § Commit L3.
    """

    loss_name: str = Field(
        min_length=1,
        description="``PLUGIN_LOSS_TYPE`` key of the plugin, e.g. "
        "``'snr_weighted_mse'``. Matches the value in "
        "``baseline_config['loss_config']['loss_name']``.",
    )
    action: Literal["reused", "generated"] = Field(
        description="``'generated'`` = implementor wrote the plugin file "
        "this iteration. ``'reused'`` = plugin already existed in the "
        "registry; no LLM call was made for the loss.",
    )
    source_iteration: str | None = Field(
        description="Which iteration originally generated this loss plugin. "
        "For ``action='generated'``: current iteration's ``run_name``. For "
        "``action='reused'``: the ``run_name`` from the registry entry "
        "(i.e. the iteration that created it, not the current one). May be "
        "``None`` for losses with no recorded origin (e.g. a hand-curated "
        "loss seeded into the registry).",
    )
    loss_file_path: str = Field(
        min_length=1,
        description="Absolute path to the loss plugin ``.py`` file. The same "
        "file regardless of action — ``'generated'`` wrote it just now, "
        "``'reused'`` is pointing at the existing one.",
    )
    dummy_tensor_validated: bool = Field(
        description="True if the implementor's dummy-tensor forward pass "
        "succeeded against the loaded plugin. Always True for "
        "``action='reused'`` (the plugin was already validated when first "
        "generated). Always True for ``action='generated'`` because the "
        "implementor only writes to disk after the dummy-tensor check "
        "passes. A False value would mean the audit trail is being "
        "recorded for a known-broken state — diagnostic only.",
    )
    contract_snapshot: CapabilityContractSnapshot | None = Field(
        default=None,
        description="Immutable contract evidence transported with the loss plugin.",
    )


class ImplementorTaskBlocks(BaseModel):
    """Task-owned IMPLEMENTOR science — prose VALUES under framework keys.

    Step 12 / PR-12a C7-4, operator-ratified as a bounded contract correction
    (the Step-12 parent §12-12a-viii already required "proposer + implementor
    task-science … caller-supplied task blocks … the corresponding optional
    section(s)"; the concrete schema is ratified here).

    Deliberately the same shape as ``InterpretationTaskBlocks`` (09b) and
    ``ProposalTaskBlocks`` (C7-3): FRAMEWORK owns the keys and where each
    renders, TASK owns the prose, every field optional, absent ⇒ NOTHING
    rendered. The three families keep SEPARATE schemas because they render in
    different places for different reasons; only their loading mechanics are
    shared.

    Two keys, not three, because the source audit showed the two role clauses
    differ only in their framing: the prompts said "deep learning for signal
    denoising" and "loss functions for signal denoising". The task owns the
    SCIENCE ("signal denoising"); the role framing around it is the
    framework's, and an undeclared task simply gets no specialism rather than
    invented prose.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    science_domain: str | None = Field(
        default=None,
        description=(
            "What this task's models actually DO, as a noun phrase — e.g. "
            "'signal denoising'. The framework frames it into the model and "
            "loss engineer role lines. Absent -> the role names no "
            "specialism, never another task's."
        ),
    )
    continuous_output_phrase: str | None = Field(
        default=None,
        description=(
            "What a CONTINUOUS (regressor) output means for this task, as it "
            "should read in generated-plugin comments — e.g. 'continuous "
            "waveform regression'. The classifier form is already derived "
            "from the declared class cardinality; this is the regressor "
            "counterpart, and 'waveform' is a task word, not a framework one. "
            "Absent -> the neutral name of the DECLARED output form is used, "
            "never TIDMAD's."
        ),
    )


class ImplementorInput(BaseModel):
    """
    Input to ml_model_implementor.

    Typically populated via ``local_full_spec`` in
    ``agent/schemas/protocols/ml_model_propose_to_ml_model_impl.py``,
    which maps ProposalOutput → ImplementorInput.
    """

    candidate_id: str | None = Field(
        default=None,
        description="V21 PR E — carried verbatim from ``ProposalOutput.candidate_id`` "
        "by the propose->impl protocol. Observational join identity only "
        "(O-E-5); None = pre-PR-E or non-proposer candidate.",
    )
    task_composition_ref: TaskCompositionRef | None = Field(
        default=None,
        description="Frozen task projection; None preserves the uncomposed legacy route.",
    )
    model_name: str = Field(
        description="snake_case model type key. Used as the filename and PLUGIN_MODEL_TYPE constant.",
    )
    output_type: OutputTypeName = Field(
        default="classifier",
        description="Output representation the proposal committed to, carried "
        "verbatim from ``ProposalOutput.output_type``. Decides the emitted "
        "``PLUGIN_OUTPUT_TYPE`` constant and the forward-contract comment, and "
        "therefore which shape the generated head must produce "
        "(``classifier`` -> [B, C, T], ``regressor`` -> [B, T]).\n"
        "Never inferred from the loss family. The default is a legacy read for "
        "fixtures; the production protocol always sets it explicitly.",
    )
    model_description: str = Field(
        description="Plain-English description of the architecture. Injected into the LLM prompt.",
    )
    mathematical_definition: str = Field(
        description="Precise layer-by-layer spec from the proposal agent. "
        "The LLM uses this to write __init__ and forward.",
    )
    baseline_config: dict[str, Any] = Field(
        description="Safe starting configuration from the proposal agent. "
        "Used to derive sensible default values for the Pydantic config fields.",
    )
    task_description: str = Field(
        default="",
        description="Plain-English description of the research task, sourced from "
        "``configs/task_config.yaml``. Injected into the ``{TASK_DESCRIPTION}`` "
        "placeholder in the implementor system prompt at call time. "
        "Default empty string is for test fixtures only; production callers "
        "(workflow) always populate via ``get_task_description(load_task_config())`` "
        "which rejects empty values upstream.",
    )
    forward_contract: ForwardContract = Field(
        default_factory=ForwardContract,
        description="Typed forward-pass contract from ``configs/task_config.yaml``. "
        "Rendered into the ``{TASK_BACKGROUND}`` placeholder in the implementor "
        "system prompt and the user-prompt contract section. Default "
        "``ForwardContract()`` (all fields empty) is for test fixtures only; "
        "production callers always populate via "
        '``ForwardContract(**load_task_config()["forward_contract"])``.',
    )
    implementor_blocks: ImplementorTaskBlocks | None = Field(
        default=None,
        description=(
            "Step 12 / PR-12a C7-4 — the run's task-owned IMPLEMENTOR "
            "science, or None. Additive and default-None by contract: every "
            "existing caller constructs this input without it. The CALLER "
            "supplies it — the workflow's bounded Regime-A adapter on an "
            "un-composed run, the composition's own declaration on a composed "
            "one. A composed run that declares NOTHING renders no science "
            "rather than inheriting TIDMAD's."
        ),
    )
    # --- Step 04a (OD-S4-1) — capacity awareness ---
    # Mirrors ``ProposalInput.hardware_context`` / ``vram_budget_gb`` exactly,
    # including their Optional-by-default shape, so the implementor's capacity
    # prose derives from the SAME live manifest the proposer already quotes
    # instead of a stale literal. No task-config field is introduced: machine
    # capacity is a property of the machine, not of the task.
    hardware_context: HardwareContext | None = Field(
        default=None,
        description="Live hardware manifest from ``core.hardware_context``, "
        "populated by the workflow via ``get_or_create``. ``None`` for "
        "CPU-only hosts, test fixtures and standalone invocations that bypass "
        "the workflow; the capacity bullet then renders its defined "
        "magnitude-free form rather than a stale ceiling.",
    )
    vram_budget_gb: float | None = Field(
        default=None,
        ge=0.0,
        description="Active operator-defined VRAM ceiling (GB) for this "
        "iteration, threaded from the workflow exactly as for the proposer. "
        "Combined with ``hardware_context`` through "
        "``HardwareContext.effective_cap_gb``, which is the single rule both "
        "nodes quote — so their prompts cannot name different caps.",
    )
    plugin_dir: str = Field(
        default="",
        description="Directory where the model plugin file will be written. "
        "An omitted value resolves below storage.local.workspace; an explicit "
        "value is preserved for orchestrators that own a narrower attempt layout.",
    )
    test_dir: str = Field(
        default="",
        description="Directory where the generated test file will be written. "
        "An omitted value resolves below storage.local.workspace; an explicit "
        "value is preserved for orchestrators that own a narrower attempt layout.",
    )
    loss_dir: str = Field(
        default="",
        description="Directory where agent-generated loss plugin files will be "
        "written when ``custom_loss_spec`` is set. Mirrors ``plugin_dir`` for "
        "model plugins. An omitted value resolves below ``storage.local.workspace``; "
        "the workflow overrides this with a per-attempt path so retries do not "
        "clobber each other's plugins. The executor resolves loss plugins from "
        "the directories listed in ``SIDERIUS_LOSS_DIRS`` (set by the sandbox "
        "executor), so writing to ``loss_dir`` is sufficient to make the new "
        "loss visible to training. See ``docs/design/enable_loss_inventory.md`` "
        "§ Commit L3.",
    )
    custom_loss_spec: CustomLossSpec | None = Field(
        default=None,
        description="Specification for a novel loss function the implementor "
        "should generate this iteration. Threaded through from "
        "``ProposalOutput.custom_loss_spec`` by the propose→impl protocol. "
        "``None`` when the proposer is using one of the four built-in losses "
        "OR when reusing a previously-registered custom loss (in which case "
        "the implementor only writes the model plugin and the loss lookup "
        "succeeds against the existing registry entry). Wiring of the actual "
        "code-generation path lives at L4.",
    )
    max_retries: int = Field(
        default=2,
        ge=0,
        description="Maximum self-correction attempts after the initial code commit. "
        "On each retry the LLM receives the validation error and its previous "
        "code, and produces a targeted fix. Total attempts = 1 + max_retries. "
        "Set to 0 to disable self-correction.",
    )
    reference_code: dict[str, str] = Field(
        default_factory=dict,
        description="Source code of referenced ancestor models. Keyed by model_type. "
        "Loaded automatically from inherited_components — the implementor "
        "uses this as a template to copy-and-modify rather than writing "
        "from scratch. Empty dict = no reference code available.",
    )
    expert_advice: ExpertAdviceInput = Field(
        default="",
        description="Structured guidance from upstream agents or orchestrators. "
        "Accepts a plain string or a structured ExpertAdvice object.",
    )
    human_advice: str | None = Field(
        default=None,
        description="Optional human-provided guidance (highest priority — overrides expert_advice). "
        "When present, injected into the LLM prompt as high-priority context.",
    )
    previous_validation_failure: str | None = Field(
        default=None,
        description="Validation error message from the previous implementation attempt "
        "for this same proposal. When set, the implementor knows upfront "
        "what spec-alignment issue to fix and can target the repair in its "
        "reasoning phase rather than discovering the problem after the fact. "
        "None on the first attempt.",
    )
    storage: StorageConfig = Field(
        default_factory=lambda: StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace="./siderius_workspace", run_name="v1"),
        ),
        description="Where this node reads its inputs and writes its own output record "
        "(e.g. implementor_output_{run_name}.json). Omitted generated-code "
        "destinations are derived from this local workspace.",
    )

    @model_validator(mode="after")
    def _resolve_generated_output_dirs(self):
        """Keep default generated code inside the caller's local workspace.

        The reference workflow supplies narrower per-attempt directories after
        constructing this object, so explicit values remain untouched. A
        standalone caller only needs to provide ``storage`` and receives an
        isolated ``generated/{run_name}`` tree instead of mutating the checkout.
        """
        missing = not self.plugin_dir or not self.test_dir or not self.loss_dir
        if not missing:
            return self
        if self.storage.backend != "local" or self.storage.local is None:
            raise ValueError(
                "plugin_dir, test_dir, and loss_dir must be explicit when "
                "storage.backend is not local"
            )
        generated_root = os.path.abspath(
            os.path.join(
                self.storage.local.workspace,
                "generated",
                self.storage.local.run_name,
            )
        )
        if not self.plugin_dir:
            self.plugin_dir = os.path.join(generated_root, "models")
        if not self.test_dir:
            self.test_dir = os.path.join(generated_root, "tests")
        if not self.loss_dir:
            self.loss_dir = os.path.join(generated_root, "losses")
        return self


class ImplementorOutput(BaseModel):
    """
    Output of ml_model_implementor.

    Paths to the written files. Consumed by ml_code_validator_agent via
    ``local_all_fields`` in
    ``agent/schemas/protocols/ml_model_impl_to_ml_model_valid.py`` to
    confirm the plugin is valid.
    """

    candidate_id: str | None = Field(
        default=None,
        description="V21 PR E — echoed verbatim from ImplementorInput. "
        "Observational join identity only (O-E-5); None = pre-PR-E or "
        "non-proposer candidate.",
    )
    model_type: str = Field(
        description="The PLUGIN_MODEL_TYPE key written into the plugin file. "
        "Same as the input model_name.",
    )
    description_file_path: str = Field(
        description="Absolute path to the written description.md "
        "(e.g. .../agent_generated/models/attn_unet/description.md). "
        "Used by result_interpretation_agent to load the model description "
        "when interpreting results from this agent-generated model.",
    )
    model_file_path: str = Field(
        description="Absolute path to the written plugin file "
        "(e.g. .../agent_generated/models/attn_unet.py).",
    )
    test_file_path: str = Field(
        description="Absolute path to the written test file "
        "(e.g. .../agent_generated/tests/test_attn_unet.py).",
    )
    config_fields: dict[str, Any] = Field(
        description="Summary of the Pydantic config fields generated by the LLM. "
        "Keys are field names, values are their default values. "
        "Used for logging and downstream context.",
    )
    model_description: str = Field(
        description="Plain-English description of the architecture, passed through from ImplementorInput. "
        "Carried forward so ml_code_validator_agent can provide it to the LLM code reviewer.",
    )
    mathematical_definition: str = Field(
        description="Precise mathematical/architectural specification from the proposal, passed through "
        "from ImplementorInput. Used by ml_code_validator_agent to verify implementation matches spec.",
    )
    baseline_config_adjustments: dict[str, ConfigAdjustment] = Field(
        default_factory=dict,
        description="Audit trail of field-level adjustments the implementor made to the "
        "proposer's baseline_config['model_config'] in order to satisfy its "
        "own pydantic schema. Empty dict (default) means the schema accepted "
        "the baseline as-is. Keys are field names; values describe the original "
        "value, the adjusted value, and the reason. Consumed by the "
        "proposal_to_hyperparam_seeded protocol to override the baseline "
        "before tuner-time, and by the interpretation agent to flag any "
        "falsifiable_prediction whose target config was mutated. "
        "See docs/improving_validation_awareness.md Phase B.1.",
    )
    loss_provenance: LossProvenance | None = Field(
        default=None,
        description="Audit trail for custom-loss usage. ``None`` when the "
        "proposer used a built-in loss type (focal, focal_cw, ce, smooth_l1). "
        "Populated when ``baseline_config['loss_config']['loss_type'] == "
        '"custom"`` — records whether the loss was reused from a prior '
        "iteration or newly generated this iteration, the source iteration's "
        "``run_name``, the absolute path to the plugin file, and whether the "
        "dummy-tensor forward pass validated. See "
        "``docs/design/enable_loss_inventory.md`` § Commit L3.",
    )
    model_probe_context: ModelProbeContext | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description="Task-owned validation input identity, transported without reinterpretation.",
    )
    model_io_contract: ModelIOContract | None = Field(
        default=None,
        description="The normalized Model-I/O contract this candidate was "
        "generated against — Step 03's semantic authority, echoed verbatim "
        "from ``ImplementorInput.forward_contract.model_io`` (Step 04a). It "
        "is carried on the OUTPUT rather than re-read downstream so the "
        "validator probes the candidate against the declaration the "
        "implementor ACTUALLY used, not against a second read of the task "
        "config that may have moved. ``None`` = the legacy prose-only "
        "compatibility path, where no normalized contract was supplied; "
        "consumers must preserve their pre-Step-04a behaviour for it and "
        "must NOT treat absence as an error.",
    )
    capability_metadata: CapabilityMetadata | None = Field(
        default=None,
        description="Registry metadata for a newly-generated model plugin, "
        "handed back to the workflow so registration happens ONLY after the "
        "validator passes. Mirrors the #92 fix for losses on the model "
        "surface: previously the implementor wrote this entry to "
        "``_capability_index.json`` immediately after generating the plugin, "
        "before the validator ran — validation failures then left phantom "
        "entries in the index that future proposers advertised as Branch B "
        "reuse candidates (v16 iter_015 ``gated_dilated_tcn`` failure mode). "
        "``None`` on Branch A (built-in) and Branch B (reuse) paths where no "
        "new plugin was generated. See ``feat/v16-fixes`` commit history and "
        "``reports/v16_20260630.md`` §9.10.",
    )
    loss_capability_metadata: CapabilityMetadata | None = Field(
        default=None,
        description="Registry metadata for a newly-generated loss plugin. "
        "The implementor returns this payload without mutating the capability "
        "index; the workflow commits it only after the complete candidate "
        "passes validation and construction admission. ``None`` means the "
        "candidate uses a built-in or already-registered loss.",
    )

    @model_validator(mode="after")
    def _enforce_adjustment_ownership(self):
        """Reject adjustments on fields the implementor does not own.

        The forbidden list (segmentation_size, ...) is the dataset-level set:
        those belong to the proposer. A violation means the wrong node is
        being retried — the error routes the retry upstream.

        This check lives here (not on ConfigAdjustment) because it depends on
        the dict key, which is not available from inside the ConfigAdjustment
        model.
        """
        for field_name in self.baseline_config_adjustments:
            if field_name in _FORBIDDEN_ADJUSTMENT_FIELDS:
                raise ValueError(
                    f"baseline_config_adjustments contains forbidden field "
                    f"'{field_name}'. This field is owned by the proposer — "
                    f"retry the proposer with a corrected value, not the "
                    f"implementor. Forbidden fields: "
                    f"{sorted(_FORBIDDEN_ADJUSTMENT_FIELDS)}."
                )
        return self
