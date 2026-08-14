"""Frozen fixtures for the Step-04a compatibility oracles.

Design: ``docs/design/generic_framework_upgrade/step_04_candidate_creation_mechanics/
pr_04a_contract_derived_candidate_mechanics.md`` §5 (Stage-A parity) and
§16 C1 (Checkpoint 0).

PR 04a makes candidate generation and candidate validation DERIVE every
contract-owned Model-I/O fact from the normalized Step-03
``ModelIOContract``. Three Stage-A surfaces had no oracle before that work
started, so they are captured here **from the unmodified production base**:

1. the bytes of a generated plugin + its generated test file, for a FIXED
   recorded spec (no LLM call — the LLM's contribution is the frozen
   ``CODE_BY_OUTPUT_TYPE`` dict below, so the template contribution is
   deterministic);
2. the validator's verdicts on a fixture plugin set;
3. the loadability of the on-disk generated-plugin corpus.

Everything a baseline feeds into production lives here so the two oracle
modules cannot drift apart: a fixture edited for one of them would silently
weaken the other.

**The spec is TIDMAD-shaped on purpose.** Stage-A asks *"is the shipped task
unchanged"*, so the fixture declares the shipped contract — ``[B, T] int64``
in, ``[B, 256, T] float32`` out — through the normalized authority, exactly
as ``configs/task_config.yaml`` does.
"""

from __future__ import annotations

from agent.schemas.implementor import ImplementorInput
from agent.schemas.model_io_contract import (
    AxisRole,
    Dimension,
    DtypeAdmissibility,
    ModelIOContract,
    TensorAxis,
    TensorContract,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.task_config import ForwardContract

#: Class cardinality of the shipped TIDMAD contract. Named once here so a
#: baseline never restates it inline — the fixtures are allowed to declare
#: the task, production is not.
TIDMAD_NUM_CLASSES = 256

#: The shipped dtype admissibilities, copied from ``configs/task_config.yaml``.
#: Both concrete integer widths are admissible at the input boundary (Step-03
#: amendment A-1); ``admissible[0]`` is the canonical rendered form.
SHIPPED_INPUT_DTYPE = DtypeAdmissibility(admissible=("int64", "int32"))
SHIPPED_OUTPUT_DTYPE = DtypeAdmissibility(admissible=("float32",))


def tidmad_model_io(num_classes: int = TIDMAD_NUM_CLASSES) -> ModelIOContract:
    """The shipped classifier contract: ``[B, T] int64 -> [B, C, T] float32``.

    ``num_classes`` is a parameter rather than a constant because the
    Stage-B cardinality rung (6.5-A) varies exactly this one axis against
    this exact baseline. Every other axis, role and dtype is held fixed.
    """
    return ModelIOContract(
        input=TensorContract(
            axes=(
                TensorAxis(dimension=Dimension(symbolic="B"), role=AxisRole.BATCH),
                TensorAxis(dimension=Dimension(symbolic="T"), role=AxisRole.TEMPORAL),
            ),
            dtype=SHIPPED_INPUT_DTYPE,
        ),
        output=TensorContract(
            axes=(
                TensorAxis(dimension=Dimension(symbolic="B"), role=AxisRole.BATCH),
                TensorAxis(dimension=Dimension(fixed=num_classes), role=AxisRole.CLASS),
                TensorAxis(dimension=Dimension(symbolic="T"), role=AxisRole.TEMPORAL),
            ),
            dtype=SHIPPED_OUTPUT_DTYPE,
        ),
    )


def regressor_model_io() -> ModelIOContract:
    """The same declaration with the class axis removed: ``[B, T] -> [B, T]``.

    This is the 6.5-C baseline — output semantic is the ONLY axis that
    differs from :func:`tidmad_model_io`, because ``output_semantic`` is
    derived from the presence of a ``class``-role axis.
    """
    return ModelIOContract(
        input=TensorContract(
            axes=(
                TensorAxis(dimension=Dimension(symbolic="B"), role=AxisRole.BATCH),
                TensorAxis(dimension=Dimension(symbolic="T"), role=AxisRole.TEMPORAL),
            ),
            dtype=SHIPPED_INPUT_DTYPE,
        ),
        output=TensorContract(
            axes=(
                TensorAxis(dimension=Dimension(symbolic="B"), role=AxisRole.BATCH),
                TensorAxis(dimension=Dimension(symbolic="T"), role=AxisRole.TEMPORAL),
            ),
            dtype=SHIPPED_OUTPUT_DTYPE,
        ),
    )


def forward_contract(model_io: ModelIOContract | None) -> ForwardContract:
    """A ``ForwardContract`` whose prose is DERIVED, never authored.

    ``model_io=None`` returns the legacy prose-only form (§15.1 row 1) with
    the shipped TIDMAD text authored directly — the shape a caller that has
    never heard of the normalized contract still produces.
    """
    if model_io is None:
        return ForwardContract(
            input_shape="[B, T] int64",
            input_description="raw signal, integer class indices 0-255",
            output_shape="[B, 256, T] float32",
            output_description="per-timestep logits over 256 denoising classes",
            num_classes=TIDMAD_NUM_CLASSES,
            task_type="classification",
        )
    return ForwardContract(
        input_description="raw signal, integer class indices 0-255",
        output_description="per-timestep logits over the denoising alphabet",
        task_type="classification",
        model_io=model_io,
    )


#: The frozen LLM contribution. In production these four strings come from
#: the code-generation call; freezing them is what makes the assembled file
#: byte-comparable at all (parent §8: "for a *fixed* spec the template
#: contribution is deterministic").
CODE_BY_OUTPUT_TYPE: dict[str, dict[str, str]] = {
    "classifier": {
        "extra_imports": "",
        "config_fields_code": "    channels: int = Field(default=16, ge=1)",
        "config_validators_code": "",
        "init_body": (
            "self.emb = nn.Embedding(256, config.channels)\n"
            "self.head = nn.Conv1d(config.channels, 256, kernel_size=1)"
        ),
        "forward_body": "out = self.emb(x).permute(0, 2, 1)\nreturn self.head(out)",
    },
    "regressor": {
        "extra_imports": "",
        "config_fields_code": "    channels: int = Field(default=16, ge=1)",
        "config_validators_code": "",
        "init_body": (
            "self.emb = nn.Embedding(256, config.channels)\n"
            "self.head = nn.Conv1d(config.channels, 1, kernel_size=1)"
        ),
        "forward_body": ("out = self.emb(x).permute(0, 2, 1)\nreturn self.head(out).squeeze(1)"),
    },
}

#: Model names are part of the generated bytes, so they are frozen too.
MODEL_NAMES: dict[str, str] = {
    "classifier": "s04a_baseline_classifier",
    "regressor": "s04a_baseline_regressor",
}


def implementor_input(
    output_type: str,
    *,
    model_io: ModelIOContract | None,
    workspace: str,
) -> ImplementorInput:
    """The frozen ``ImplementorInput`` both oracles render from.

    Args:
        output_type: ``"classifier"`` or ``"regressor"`` — the proposal's
            declared output representation.
        model_io: the normalized contract to supply, or ``None`` for the
            legacy prose-only compatibility path.
        workspace: a ``tmp_path``-derived storage workspace. It never
            reaches the assembled bytes; ``plugin_dir``/``test_dir`` do not
            either, but they are pointed at the workspace so nothing can
            write into the live ``agent_generated/`` tree.
    """
    return ImplementorInput(
        model_name=MODEL_NAMES[output_type],
        output_type=output_type,
        model_description=f"Frozen Step-04a {output_type} baseline candidate.",
        mathematical_definition=(
            "Embedding(256, C) -> permute -> Conv1d(C, out, 1). Frozen fixture."
        ),
        baseline_config={
            "model_config": {"channels": 16, "segmentation_size": 4000},
            "train_config": {"lr": 5e-4, "epochs": 1, "batch_size": 2},
            "loss_config": {"loss_type": "focal" if output_type == "classifier" else "smooth_l1"},
        },
        task_description="Frozen Step-04a task description fixture.",
        forward_contract=forward_contract(model_io),
        plugin_dir=f"{workspace}/models",
        test_dir=f"{workspace}/tests",
        loss_dir=f"{workspace}/losses",
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=workspace, run_name="s04a"),
        ),
    )
