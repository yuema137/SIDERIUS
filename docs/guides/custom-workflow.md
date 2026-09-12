# Assemble a custom workflow boundary

**Audience**: task authors who need to call an existing node boundary from a
caller-owned workflow.

SIDERIUS already provides typed adapters for the common node handoffs. The
adapter below is deterministic: it validates a proposal, maps its model
specification into `ImplementorInput`, and leaves the caller in control of the
workspace and task context. It does not invoke an LLM or execute a node.

```python
from pathlib import Path

from agent.schemas.implementor import ImplementorInput
from agent.schemas.proposal import ExpertAdvice, FalsifiablePrediction, ProposalOutput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.task_config import ForwardContract
from agent.schemas.protocols.ml_model_propose_to_ml_model_impl import local_full_spec

workspace = Path("/tmp/my-task-workspace")
storage = StorageConfig(
    backend="local",
    local=LocalStorageConfig(workspace=str(workspace), run_name="demo"),
)
proposal = ProposalOutput(
    model_name="demo_model",
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
# transport task context: attach the resolved run declaration at this boundary.
implementor = local_full_spec(proposal, storage).model_copy(update={
    "task_description": "The caller's declared supervised task.",
    "forward_contract": ForwardContract(
        input_shape="[B, T] float32",
        input_description="caller-declared features",
        output_shape="[B, 1] float32",
        output_description="caller-declared prediction",
    ),
})
assert isinstance(implementor, ImplementorInput)
assert implementor.storage == storage
assert implementor.task_description.startswith("The caller")
assert implementor.forward_contract.output_shape == "[B, 1] float32"
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
then validate records at the next boundary.

See the [task declaration guide](define-a-task.md), the
[composition reference](../reference/task-composition.md), and the
[node contracts](../agent-reference/README.md#nodes) for complete fields and
route-specific limitations.
