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

## Existing entrypoints and parameters

Python import: `nodes.ml_model_proposal_agent.ml_model_proposal_agent.MLModelProposalAgent`.
Native constructor at reference revision `2df46e22`:

```text
MLModelProposalAgent(provider: str='gemini', model_id: str='gemini-3.1-flash-lite-preview', max_retries: int | None=None, reasoning_effort: str | None=None, bridge_factory=None, capability_index_path: str | None=None, **kwargs)
```

`bridge_factory` is existing dependency injection, not a model-provider choice.
Use production defaults unless the declared execution environment supplies one.
Frozen routing/limits/access policy belong to the run descriptor. The orchestrator
may choose only parameters left open there; schema defaults do not override it.

[CLI flags](../cli/proposer.md)

Standalone CLI uses the legacy entry path and lacks the full Python context. Constructor **kwargs do not establish per-stage routing: the implementation explicitly leaves those future stage overrides unused. Configure only supported provider fields and the declared reasoning pipeline.

## Single native call

The caller supplies an already assembled request JSON from authorized artifacts.
This function validates it, performs one actual call and saves the typed return.
It does not synthesize task context, provision dependencies or choose a workflow.
Use the run's Python with generated-library and task binding as described in
[invocation](../invocation.md), before importing nodes that inspect registries.
The request JSON fields and their origins are described above and in the field
inventory. Use a distinct result_path in caller-owned storage.

```python
from pathlib import Path
from agent.schemas.proposal import ProposalInput, ProposalOutput
from nodes.ml_model_proposal_agent.ml_model_proposal_agent import MLModelProposalAgent


def invoke(request_path, result_path, *, provider, model_id, reasoning_effort=None):
    request = ProposalInput.model_validate_json(Path(request_path).read_text())
    node = MLModelProposalAgent(provider=provider, model_id=model_id,
        reasoning_effort=reasoning_effort)
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
