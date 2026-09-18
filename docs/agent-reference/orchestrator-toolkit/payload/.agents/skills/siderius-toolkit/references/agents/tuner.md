# tuner: one existing capability

## Capability and prerequisites

Plan and execute tuning, training and evaluation through existing task bindings. Returns run records, selected results and resource/validity feedback.

Before calling, read [shared invocation](../invocation.md),
[artifact/concurrency effects](../artifacts-and-concurrency.md), and the
[native input/output field inventory](../schemas/tuner.md). The inventory lists
required fields, optional fields, types, generic defaults and constraints;
its native-schema inspection shows all nested models. Custom validation remains
authoritative. Schema descriptions can retain historical examples: the active
task contract, not an example or fallback, supplies scientific semantics.

model_type is the schema-required field, but a runnable task needs the correct installed candidate, bound task composition, data root, storage, metric/Health configuration and resource settings. Provider/model/effort and reflection routing are input fields, not constructor kwargs. Formal training ownership and Formal evaluation scope are separate controls.

## Existing entrypoints and parameters

Python import: `nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent.HyperparamTuningAgent`.
Native constructor at reference revision `1c68bc81`:

```text
HyperparamTuningAgent(bridge_factory=None, sandbox_factory=None, capability_index_path: str | None=None)
```

`bridge_factory` is existing dependency injection, not a model-provider choice.
Use production defaults unless the declared execution environment supplies one.
Frozen routing/limits/access policy belong to the run descriptor. The orchestrator
may choose only parameters left open there; schema defaults do not override it.

[CLI flags](../cli/tuner.md)

The public module has an extensive standalone CLI, listed separately. The private cli.py file is parser provenance, not a new supported import API. No JSON-universal invoker is installed by this documentation.

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
from agent.schemas.hyperparam_tuning import HyperparamTuningInput, HyperparamTuningOutput
from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import HyperparamTuningAgent


def invoke(request_path, result_path):
    request = HyperparamTuningInput.model_validate_json(Path(request_path).read_text())
    node = HyperparamTuningAgent()
    result = node.run(request)
    if not isinstance(result, HyperparamTuningOutput):
        raise TypeError("Unexpected native output type")
    Path(result_path).write_text(result.model_dump_json(indent=2))
    return result
```

Expected output is `HyperparamTuningOutput`, not an unvalidated dictionary. See its field table
for exact shape, required fields and status/diagnostic metadata. The example's
explicit result file is caller persistence; native node side effects still apply.
For typed transfer to another capability, read [handoffs](../handoffs.md).

## Files, repeated calls and concurrency

May create sandbox processes, train, infer, score, publish records and clean artifacts. These share the run budget. Explicitly configure preservation to meet the task submission contract. Call set_run_context when native tuner telemetry is required; do not claim comprehensive accounting merely from run().

## Errors and recovery

Preserve partial results, gate exhaustion, Health and termination metadata. A selected training result is not automatically an eligible final submission. For agent-owned Formal training, the validated plan supplies training strategy/portions; the task still owns evaluation. Missing executor access is not solved by exposing private evaluator assets.

Input validation, missing task bindings, provider failures and scientific failure
are distinct outcomes. Retrying consumes the same resources and clock. Preserve
the actual error and input identity; do not broaden permissions or invent success.
