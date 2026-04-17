# agent/schemas/implementor.py
"""
Input and output schemas for ml_model_implementor.

This node consumes a ProposalOutput and produces a validated plugin file
and test file in agent_generated/. It does not register the plugin itself —
that is verified by code_validator_agent.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, model_validator

from agent.schemas.storage import StorageConfig, LocalStorageConfig
from agent.schemas.hyperparam_tuning import ExpertAdviceInput


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


class ImplementorInput(BaseModel):
    """
    Input to ml_model_implementor.

    Typically populated via the proposal_to_implementor_v1 protocol,
    which maps ProposalOutput → ImplementorInput.
    """

    model_name: str = Field(
        description="snake_case model type key. Used as the filename and PLUGIN_MODEL_TYPE constant.",
    )
    model_description: str = Field(
        description="Plain-English description of the architecture. Injected into the LLM prompt.",
    )
    mathematical_definition: str = Field(
        description="Precise layer-by-layer spec from the proposal agent. "
                    "The LLM uses this to write __init__ and forward.",
    )
    baseline_config: Dict[str, Any] = Field(
        description="Safe starting configuration from the proposal agent. "
                    "Used to derive sensible default values for the Pydantic config fields.",
    )
    plugin_dir: str = Field(
        default="agent_generated/models",
        description="Directory where the model plugin file will be written. "
                    "This is a fixed output destination independent of storage.local.workspace.",
    )
    test_dir: str = Field(
        default="agent_generated/tests",
        description="Directory where the test file will be written. "
                    "This is a fixed output destination independent of storage.local.workspace.",
    )
    max_retries: int = Field(
        default=2,
        ge=0,
        description="Maximum self-correction attempts after the initial code commit. "
                    "On each retry the LLM receives the validation error and its previous "
                    "code, and produces a targeted fix. Total attempts = 1 + max_retries. "
                    "Set to 0 to disable self-correction.",
    )
    reference_code: Dict[str, str] = Field(
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
    human_advice: Optional[str] = Field(
        default=None,
        description="Optional human-provided guidance (highest priority — overrides expert_advice). "
                    "When present, injected into the LLM prompt as high-priority context.",
    )
    previous_validation_failure: Optional[str] = Field(
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
                    "(e.g. implementor_output_{run_name}.json). "
                    "Note: plugin_dir and test_dir are separate — they are fixed "
                    "code output destinations, not part of the workspace.",
    )


class ImplementorOutput(BaseModel):
    """
    Output of ml_model_implementor.

    Paths to the written files. Consumed by code_validator_agent
    via implementor_to_validator_v1 to confirm the plugin is valid.
    """

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
    config_fields: Dict[str, Any] = Field(
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
    baseline_config_adjustments: Dict[str, ConfigAdjustment] = Field(
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
