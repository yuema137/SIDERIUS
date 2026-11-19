# proposer: one existing capability

## Capability and prerequisites

Produce a typed model proposal from interpretation and optional authorized evidence. One call returns one native proposal; call count and branch choice belong to the orchestrator.

Before calling, read [shared invocation](../invocation.md),
[artifact/concurrency effects](../artifacts-and-concurrency.md), and the
[native input/output field inventory](../schemas/proposer.md). The inventory lists
required fields, optional fields, types, generic defaults and constraints;
its native-schema inspection shows all nested models. Custom validation remains
authoritative. Schema descriptions can retain historical examples: the active
task contract, not an example or fallback, supplies scientific semantics.

interpretation_evidence is required and is a typed projection, not an arbitrary prose string. Supply task description, forward contract, task composition reference, hardware, permitted advice and parameter rules from their declared owners. Optional expert_context and reasoning_pipeline allow richer reasoning; defaults do not populate the complete scientific contract.

Before invoking, check the [actual serialized request](../invocation.md#check-the-request-you-will-actually-send),
including the run's applicable scope and the source of any advice fields.
Save the check and started status before the call; update its outcome before
preparing another operation.

## Existing entrypoints and parameters

Python import: `nodes.ml_model_proposal_agent.ml_model_proposal_agent.MLModelProposalAgent`.
Native constructor, generated from the class source (a computed default shows
its value in parentheses). `transport` is the optional OpenAI background-mode
route carrier (see the workflow `openai_background` setting):

<!-- generated: constructor nodes.ml_model_proposal_agent.ml_model_proposal_agent.MLModelProposalAgent -->
```text
MLModelProposalAgent(provider: str=PROPOSE.provider (= 'openai'), model_id: str | None=PROPOSE.model_id (= None), max_retries: int | None=PROPOSE.max_retries (= None), reasoning_effort: str | None=PROPOSE.reasoning_effort (= None), bridge_factory=None, capability_index_path: str | None=None, max_output_tokens: int | None=None, transport: PydanticTransportConfig | None=None, **kwargs)
```
<!-- end generated -->

`bridge_factory` is existing dependency injection, not a model-provider choice.
Use production defaults unless the declared execution environment supplies one.
Frozen routing/limits/access policy belong to the run descriptor. The orchestrator
may choose only parameters left open there; schema defaults do not override it.

[CLI flags](../cli/proposer.md)

### Stage model routing

The constructor's `provider`, `model_id`, `reasoning_effort`,
`max_output_tokens`, `max_retries` and `transport` form the legacy constructor
route. `**kwargs` accepts flat per-stage overrides named `{stage}_{field}`, where
`stage` is `comparison`, `reasoning` or `proposing` and `field` is one of those
six names: for example `comparison_model_id`, `reasoning_reasoning_effort` or
`proposing_max_retries`. `resolve_proposer_routing` applies them once at
construction. A key that is absent inherits the legacy constructor value. A
supplied value replaces it, including `None` or `0` where the field allows it
(for example `proposing_model_id=None` or `comparison_max_retries=0`). Each
resolved route is validated as a `ProposerRoute`, so an invalid value such as
`proposing_provider=None` or `proposing_max_output_tokens=0` raises a
`ValidationError` at construction. Keyword names outside this pattern are
refused at construction: the flat options are validated against
`nodes.proposer_routing.ProposerStageOptions` (one optional field per
`{stage}_{field}`, extra keys forbidden), and an unknown key raises
`UnknownProposerStageOption` (a `TypeError`) whose `unknown` attribute and
message name the key and list every accepted option. No bridge is constructed
before the refusal. After construction, read the immutable `node.routing`
(`ProposerRouting` with `comparison`, `reasoning` and `proposing` routes) to
confirm what will be used.

Stages use their routes as follows:

| Route | Calls |
| --- | --- |
| `comparison` | Comparison stage, including its vocabulary corrections |
| `reasoning` | `causal_reasoning` stage with its boldness retries and corrections; any other stage in `reasoning_pipeline.stages`; both calls of legacy two-call mode |
| `proposing` | Final proposing stage, including its structural retries |

`node.bridge` is the eager bridge for the `reasoning` route. A stage whose
route equals the `reasoning` route uses `node.bridge`. Any other route gets
its own bridge from `bridge_factory` when that stage first runs; stages with an
identical route share it. Legacy two-call mode (no enabled stage in
`reasoning_pipeline`) uses only `node.bridge`.

The fixed workflow constructs this agent as
`MLModelProposalAgent(**llm_config.get("propose"), bridge_factory=...)`.
`WorkflowLLMConfig.get("propose")` flattens the `propose.comparison`,
`propose.reasoning` and `propose.proposing` entries of a workflow LLM profile
into these keys and sets the legacy constructor route from
`propose.reasoning`; a profile without a `propose` entry yields an empty
mapping, so constructor defaults apply. When the run declaration supplies such
a profile, pass the same mapping, for example
`MLModelProposalAgent(**WorkflowLLMConfig.from_json(profile_path).get("propose"))`
with `WorkflowLLMConfig` from `workflows.llm_config`. Otherwise pass the
declared per-stage values as the flat keys above.

The standalone CLI constructs the agent with only `--provider` and
`--model_id`, so every stage uses that one route with the constructor defaults
for effort, retries and output limit. It builds `ProposalInput` without a
`reasoning_pipeline`, which selects legacy two-call mode, and it binds no run
context. Use the Python API for stage routing, a reasoning pipeline or token
recording.

### Token recording

Bind recording with the proposer's own method,
`node.set_run_context(workspace=..., iter=..., run_name=..., run_id=...)`,
before `run()`. It binds `node.bridge` and any stage bridges already created,
and keeps the context to bind each later stage bridge before its first call.
Do not call `node.bridge.set_run_context(...)` for the proposer: that binds only
the `reasoning` bridge. Calls on separately routed stages still reach the
provider but write no `token_usage.jsonl` rows, because an unbound bridge
records nothing. Shared preconditions are in
[configuration and observations](../invocation.md#configuration-and-observations).

## Single native call

The caller supplies an already validated native request from authorized artifacts.
For persisted composed requests, first apply [composition recovery](../invocation.md#restore-persisted-composition-references-before-execution).
This function preserves that native object, performs one actual call and saves the typed return.
It does not synthesize task context, provision dependencies or choose a workflow.
Use the run's Python with generated-library and task binding as described in
[invocation](../invocation.md), before importing nodes that inspect registries.
The request fields and their origins are described above and in the field
inventory. Use a distinct result_path in caller-owned storage.

```python
from pathlib import Path
from agent.schemas.proposal import ProposalInput, ProposalOutput
from nodes.ml_model_proposal_agent.ml_model_proposal_agent import MLModelProposalAgent


def invoke(request: ProposalInput, result_path, *, routing, run_context=None):
    if not isinstance(request, ProposalInput):
        raise TypeError("Assemble or restore the native request before invocation")
    # routing: the complete constructor routing keywords, either
    # WorkflowLLMConfig.from_json(profile_path).get("propose") or the declared
    # {"provider": ..., "model_id": ..., "proposing_model_id": ..., ...} values.
    node = MLModelProposalAgent(**routing)
    if run_context is not None:
        # The four keywords workspace/iter/run_name/run_id; binds every stage bridge.
        node.set_run_context(**run_context)
    result = node.run(request)
    if not isinstance(result, ProposalOutput):
        raise TypeError("Unexpected native output type")
    Path(result_path).write_text(result.model_dump_json(indent=2))
    return result
```

Expected output is `ProposalOutput`, not an unvalidated dictionary. See its field table
for exact shape, required fields and status/diagnostic metadata. The example's
explicit result file is caller persistence; native node side effects still apply.
For typed transfer to another capability, read [handoffs](../handoffs.md).

## Files, repeated calls and concurrency

May read the run-bound model/loss registry and capability index; writes proposal records under storage. Generated candidate_id is an observational identity. Preserve it with the proposal and disambiguate output storage for independent calls.

## Errors and recovery

Carry prior validation failures and bounded tune feedback through their typed fields when relevant. Preserve a failed proposal call as a failure; do not invent an output or assign a candidate ID yourself.

Input validation, missing task bindings, provider failures and scientific failure
are distinct outcomes. Retrying consumes the same resources and clock. Preserve
the actual error and input identity; do not broaden permissions or invent success.
