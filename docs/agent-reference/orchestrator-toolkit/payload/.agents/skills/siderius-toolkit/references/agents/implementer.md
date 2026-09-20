# implementer: one existing capability

## Capability and prerequisites

Generate candidate model code, tests, descriptions and optional loss code from one concrete proposal and task contract.

Before calling, read [shared invocation](../invocation.md),
[artifact/concurrency effects](../artifacts-and-concurrency.md), and the
[native input/output field inventory](../schemas/implementer.md). The inventory lists
required fields, optional fields, types, generic defaults and constraints;
its native-schema inspection shows all nested models. Custom validation remains
authoritative. Schema descriptions can retain historical examples: the active
task contract, not an example or fallback, supplies scientific semantics.

Required inputs are model_name, model_description, mathematical_definition and baseline_config. Use the proposal protocol, then supply forward_contract (including its model_io), task context, permitted reference code and recovery feedback as applicable. Set explicit run-owned model/loss/test destinations using the native fields.

Before invoking, check the [actual serialized request](../invocation.md#check-the-request-you-will-actually-send),
including the run's applicable scope and the source of any advice fields.
Save the check and started status before the call; update its outcome before
preparing another operation.

## Deployment handoff

Before connecting a generated model to substantial training, read the submission
and execution guide named by `SIDERIUS-RUN.md`. If it supplies a format/device
compatibility checker, use that checker on the selected model and configuration;
the generic implementor and validator do not automatically run an external
submission check. Generated code can train successfully yet fail serialization
or execution on the evaluator's device. Pass the concrete compatibility error
through the existing repair input. The deployment owns the format and devices;
this toolkit does not choose them or prescribe a scientific model.

## Existing entrypoints and parameters

Python import: `nodes.ml_model_implementor.ml_model_implementor.MLModelImplementor`.
Native constructor at reference revision `1c68bc81`:

```text
MLModelImplementor(provider: str='gemini', model_id: str='gemini-3.1-pro-preview', max_retries: int | None=None, reasoning_effort: str | None=None, bridge_factory=None, capability_index_path: str | None=None, **kwargs)
```

`bridge_factory` is existing dependency injection, not a model-provider choice.
Use production defaults unless the declared execution environment supplies one.
Frozen routing/limits/access policy belong to the run descriptor. The orchestrator
may choose only parameters left open there; schema defaults do not override it.

[CLI flags](../cli/implementer.md)

Standalone CLI reads proposal JSON and exposes only minimal configuration. It omits rich task context, human advice, reference-code and retry feedback available in Python. Do not assume CLI parity with the API.

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
from agent.schemas.implementor import ImplementorInput, ImplementorOutput
from nodes.ml_model_implementor.ml_model_implementor import MLModelImplementor


def invoke(request: ImplementorInput, result_path, *, provider, model_id, reasoning_effort=None):
    if not isinstance(request, ImplementorInput):
        raise TypeError("Assemble or restore the native request before invocation")
    node = MLModelImplementor(provider=provider, model_id=model_id,
        reasoning_effort=reasoning_effort)
    result = node.run(request)
    if not isinstance(result, ImplementorOutput):
        raise TypeError("Unexpected native output type")
    Path(result_path).write_text(result.model_dump_json(indent=2))
    return result
```

Expected output is `ImplementorOutput`, not an unvalidated dictionary. See its field table
for exact shape, required fields and status/diagnostic metadata. The example's
explicit result file is caller persistence; native node side effects still apply.
For typed transfer to another capability, read [handoffs](../handoffs.md).

## Files, repeated calls and concurrency

Writes generated code and tests, may run probes and repair attempts, and persists implementor output. Candidate generation uses the bound generated library; overlapping candidates need disjoint paths and coordinated registry publication. It is an effectful code-generation call.

### Generated test import paths

At the reference revision, the test-generation prompt contains a sibling
`../models` import-path example. Supplying an arbitrary `plugin_dir` such as
`attempt/plugin` can still produce tests that import from `attempt/models`.
One compatible caller-owned layout, when the run leaves paths open, is:

```text
attempt/
  models/    plugin_dir
  tests/     test_dir
  losses/    loss_dir, if needed
```

Verify the returned test's import path against the actual model artifact. This
layout addresses an existing prompt assumption; it is not a guarantee that
all generated tests pass. Preserve failed results and send actual diagnostics
to the existing repair input when another call is authorized. After any local
artifact change, prior validation does not certify the changed bytes; separate
any local test result from the native validation verdict.

## Errors and recovery

Feed actual validator diagnostic evidence to a supported retry input when repairing. A returned artifact path is not a validation pass or scientific score. Preserve candidate identity and the realized model I/O contract across the handoff.

Input validation, missing task bindings, provider failures and scientific failure
are distinct outcomes. Retrying consumes the same resources and clock. Preserve
the actual error and input identity; do not broaden permissions or invent success.
