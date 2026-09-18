# interpretation: one existing capability

## Capability and prerequisites

Interpret typed experimental summaries and return structured evidence. An explicit cold start represents absence of prior runs.

Before calling, read [shared invocation](../invocation.md),
[artifact/concurrency effects](../artifacts-and-concurrency.md), and the
[native input/output field inventory](../schemas/interpretation.md). The inventory lists
required fields, optional fields, types, generic defaults and constraints;
its native-schema inspection shows all nested models. Custom validation remains
authoritative. Schema descriptions can retain historical examples: the active
task contract, not an example or fallback, supplies scientific semantics.

Use cold_start=True only when there is no prior experimental evidence. Otherwise supply native summaries and the bound metric specification for score-bearing history. Carry task interpretation blocks, Health context and vocabulary state when applicable. Empty lists alone do not authorize a fabricated cold start.

## Existing entrypoints and parameters

Python import: `nodes.result_interpretation_agent.result_interpretation_agent.ResultInterpretationAgent`.
Native constructor at reference revision `2df46e22`:

```text
ResultInterpretationAgent(provider: str='gemini', model_id: str='gemini-3.1-flash-lite-preview', max_retries: int | None=None, reasoning_effort: str | None=None, bridge_factory=None, **kwargs)
```

`bridge_factory` is existing dependency injection, not a model-provider choice.
Use production defaults unless the declared execution environment supplies one.
Frozen routing/limits/access policy belong to the run descriptor. The orchestrator
may choose only parameters left open there; schema defaults do not override it.

[CLI flags](../cli/interpretation.md)

The CLI consumes a stored summary and model_type; it does not expose the complete typed history and task-context surface. Use the API for richer context or cold-start input.

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
from agent.schemas.interpretation import InterpretationInput, InterpretationOutput
from nodes.result_interpretation_agent.result_interpretation_agent import ResultInterpretationAgent


def invoke(request_path, result_path, *, provider, model_id, reasoning_effort=None):
    request = InterpretationInput.model_validate_json(Path(request_path).read_text())
    node = ResultInterpretationAgent(provider=provider, model_id=model_id,
        reasoning_effort=reasoning_effort)
    result = node.run(request)
    if not isinstance(result, InterpretationOutput):
        raise TypeError("Unexpected native output type")
    Path(result_path).write_text(result.model_dump_json(indent=2))
    return result
```

Expected output is `InterpretationOutput`, not an unvalidated dictionary. See its field table
for exact shape, required fields and status/diagnostic metadata. The example's
explicit result file is caller persistence; native node side effects still apply.
For typed transfer to another capability, read [handoffs](../handoffs.md).

## Files, repeated calls and concurrency

The explicit cold-start branch returns deterministic evidence without a model call unless an analysis brief is requested. Other branches may use the provider. Python callers retain returned output explicitly; do not assume every branch persists a file.

## Errors and recovery

Preserve cold_start and degraded/status evidence. Metric direction comes from the task metric specification, not a local higher-is-better assumption. Retry provider failures without changing the evidence into successful experiments.

Input validation, missing task bindings, provider failures and scientific failure
are distinct outcomes. Retrying consumes the same resources and clock. Preserve
the actual error and input identity; do not broaden permissions or invent success.
