# validator: one existing capability

## Capability and prerequisites

Check generated candidate code, tests, config and model I/O; return a typed verdict with diagnostics. This executes candidate code and tests.

Before calling, read [shared invocation](../invocation.md),
[artifact/concurrency effects](../artifacts-and-concurrency.md), and the
[native input/output field inventory](../schemas/validator.md). The inventory lists
required fields, optional fields, types, generic defaults and constraints;
its native-schema inspection shows all nested models. Custom validation remains
authoritative. Schema descriptions can retain historical examples: the active
task contract, not an example or fallback, supplies scientific semantics.

Required fields name model_type, model/test/description paths, config_fields, model_description and mathematical_definition. Carry model_io_contract and candidate_id from implementation. Provider configuration on inputs and constructor must use the run routing; field presence does not automatically configure a constructor.

## Existing entrypoints and parameters

Python import: `nodes.ml_code_validator_agent.ml_code_validator_agent.MLCodeValidatorAgent`.
Native constructor at reference revision `2df46e22`:

```text
MLCodeValidatorAgent(provider: str='gemini', model_id: str='gemini-3.1-flash-lite-preview', max_retries: int | None=None, reasoning_effort: str | None=None, bridge_factory=None, **kwargs)
```

`bridge_factory` is existing dependency injection, not a model-provider choice.
Use production defaults unless the declared execution environment supplies one.
Frozen routing/limits/access policy belong to the run descriptor. The orchestrator
may choose only parameters left open there; schema defaults do not override it.

[CLI flags](../cli/validator.md)

CLI lacks the complete model I/O and inheritance context. Its config_fields argument is a JSON object. The Python API preserves typed context from implementation.

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
from agent.schemas.validator import ValidatorInput, ValidatorOutput
from nodes.ml_code_validator_agent.ml_code_validator_agent import MLCodeValidatorAgent


def invoke(request_path, result_path, *, provider, model_id, reasoning_effort=None):
    request = ValidatorInput.model_validate_json(Path(request_path).read_text())
    node = MLCodeValidatorAgent(provider=provider, model_id=model_id,
        reasoning_effort=reasoning_effort)
    result = node.run(request)
    if not isinstance(result, ValidatorOutput):
        raise TypeError("Unexpected native output type")
    Path(result_path).write_text(result.model_dump_json(indent=2))
    return result
```

Expected output is `ValidatorOutput`, not an unvalidated dictionary. See its field table
for exact shape, required fields and status/diagnostic metadata. The example's
explicit result file is caller persistence; native node side effects still apply.
For typed transfer to another capability, read [handoffs](../handoffs.md).

## Files, repeated calls and concurrency

Imports candidate plugins, runs pytest and structural/gradient checks, and may use model-assisted checks. The execution environment must already permit these effects. Process separation alone does not isolate shared registry/filesystem mutations.

## Errors and recovery

Inspect passed and diagnostic fields. A schema-valid ValidatorOutput with passed=False cannot take the validated-model handoff. Repair using actual errors; never turn a failed validator into a successful training prerequisite.

Input validation, missing task bindings, provider failures and scientific failure
are distinct outcomes. Retrying consumes the same resources and clock. Preserve
the actual error and input identity; do not broaden permissions or invent success.
