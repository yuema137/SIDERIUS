# Assemble a custom workflow boundary

SIDERIUS already provides typed adapters for the common node handoffs. The
adapter below is deterministic: it validates a proposal, maps its model
specification into `ImplementorInput`, and leaves the caller in control of the
workspace and task context. It does not invoke an LLM or execute a node.

```python
import tempfile
from pathlib import Path

from agent.schemas.implementor import ImplementorInput
from agent.schemas.proposal import ExpertAdvice, FalsifiablePrediction, ProposalOutput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.task_config import ForwardContract
from agent.schemas.implementor import ImplementorTaskBlocks
from agent.schemas.model_io_contract import Dimension, ModelIOContract, TensorAxis, TensorContract
from ml_models.models_format_sandbox import DtypeAdmissibility
from agent.schemas.protocols.ml_model_propose_to_ml_model_impl import local_full_spec

workspace = Path(tempfile.mkdtemp(prefix="siderius-custom-workflow-"))
storage = StorageConfig(
    backend="local",
    local=LocalStorageConfig(workspace=str(workspace), run_name="demo"),
)
proposal = ProposalOutput(
    model_name="demo_model",
    output_type="regressor",
    model_description="A small model for the declared task.",
    mathematical_definition="Input projection followed by a linear prediction head.",
    motivation="Tests the typed handoff.",
    expert_advice=ExpertAdvice(focus_areas=["keep the baseline small"]),
    baseline_config={"width": 8},
    falsifiable_prediction=FalsifiablePrediction(
        metric="demo_metric", current_value=0.5, predicted_value=0.6,
        threshold_for_refutation=0.4, rationale="A measurable improvement.",
    ),
    predicted_failure_modes=["insufficient capacity"],
)

# The adapter carries proposal fields and caller-owned storage. It does not
# transport task context: attach the resolved run declaration at this boundary,
# then revalidate the complete typed object.
model_io = ModelIOContract(
    input=TensorContract(
        axes=(TensorAxis(dimension=Dimension(symbolic="B")),
              TensorAxis(dimension=Dimension(symbolic="T"))),
        dtype=DtypeAdmissibility(admissible=("float32",)),
    ),
    output=TensorContract(
        axes=(TensorAxis(dimension=Dimension(symbolic="B")),
              TensorAxis(dimension=Dimension(fixed=1))),
        dtype=DtypeAdmissibility(admissible=("float32",)),
    ),
)
implementor = local_full_spec(proposal, storage).model_copy(update={
    "task_description": "The caller's declared supervised task.",
    "plugin_dir": str(workspace / "generated" / "models"),
    "forward_contract": ForwardContract(
        input_description="caller-declared features",
        output_description="caller-declared prediction",
        model_io=model_io,
    ),
    "implementor_blocks": ImplementorTaskBlocks(
        science_domain="demo prediction", continuous_output_phrase="demo value"
    ),
})
implementor = ImplementorInput.model_validate(implementor.model_dump())
assert isinstance(implementor, ImplementorInput)
assert implementor.storage == storage
assert implementor.model_name == proposal.model_name
assert implementor.output_type == "regressor"
assert implementor.baseline_config == proposal.baseline_config
assert implementor.plugin_dir.startswith(str(workspace))
assert implementor.task_description.startswith("The caller")
assert implementor.forward_contract.input_shape == "[B, T] float32"
assert implementor.forward_contract.output_shape == "[B, 1] float32"
assert implementor.forward_contract.model_io == model_io
assert implementor.implementor_blocks is not None
```

In a real composed run, `task_description`, `forward_contract` and optional
`implementor_blocks` come from the resolved `RunTaskComposition`, not from a
framework default. The example uses synthetic declarations only to show the
typed assembly boundary. A caller may now invoke the implementor with this
input, but that is an effectful LLM/filesystem operation and is intentionally
outside this deterministic example.

`StorageConfig` describes where the node records its own inputs and outputs; it
is not an inter-node message channel. Typed protocol adapters carry values in
memory. If a workflow needs persistence, it must use the declared storage and
then validate records at the next boundary. The temporary workspace above is
created by the caller and can be removed after the demonstration.

See the [task declaration guide](define-a-task.md), the
[composition reference](../reference/task-composition.md), and the
[node contracts](../agent-reference/index.md#nodes) for complete fields and
route-specific limitations.
