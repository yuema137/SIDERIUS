# data-analysis: one existing capability

## Capability and prerequisites

Execute scoped scientific analysis through a task-supplied capability and report measured findings. Availability depends on an actual callable analysis binding.

Before calling, read [shared invocation](../invocation.md),
[artifact/concurrency effects](../artifacts-and-concurrency.md), and the
[native input/output field inventory](../schemas/data-analysis.md). The inventory lists
required fields, optional fields, types, generic defaults and constraints;
its native-schema inspection shows all nested models. Custom validation remains
authoritative. Schema descriptions can retain historical examples: the active
task contract, not an example or fallback, supplies scientific semantics.

Supply request identity, assets, access policy, analysis envelope, questions and authorized skill packs as required by the native schema. The constructor requires task_analysis_capability; a JSON description cannot substitute for this executable dependency. Historical model inference is a separate optional capability.

## Existing entrypoints and parameters

Python import: `nodes.data_analysis_agent.data_analysis_agent.DataAnalysisAgent`.
Native constructor at reference revision `1c68bc81`:

```text
DataAnalysisAgent(*, task_analysis_capability: TaskAnalysisCapability, provider: str='gemini', model_id: str | None=None, max_retries: int | None=None, reasoning_effort: str | None=None, bridge_factory: Callable[..., object] | None=None, historical_model_inference_capability: HistoricalModelInferenceCapability | None=None)
```

`bridge_factory` is existing dependency injection, not a model-provider choice.
Use production defaults unless the declared execution environment supplies one.
Frozen routing/limits/access policy belong to the run descriptor. The orchestrator
may choose only parameters left open there; schema defaults do not override it.

No CLI flags: no standalone CLI exists.

There is no standalone Data Analysis CLI at this revision. Use its Python API in an authorized executor. The analysis capability must materialize only permitted data and enforce the declared scope; this skill supplies no such capability.

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
from agent.schemas.data_analysis import DataAnalysisInput, DataAnalysisReport
from nodes.data_analysis_agent.data_analysis_agent import DataAnalysisAgent


def invoke(request_path, result_path, *, task_analysis_capability, provider, model_id, reasoning_effort=None):
    request = DataAnalysisInput.model_validate_json(Path(request_path).read_text())
    node = DataAnalysisAgent(task_analysis_capability=task_analysis_capability,
        provider=provider, model_id=model_id, reasoning_effort=reasoning_effort)
    result = node.run(request)
    if not isinstance(result, DataAnalysisReport):
        raise TypeError("Unexpected native output type")
    Path(result_path).write_text(result.model_dump_json(indent=2))
    return result
```

Expected output is `DataAnalysisReport`, not an unvalidated dictionary. See its field table
for exact shape, required fields and status/diagnostic metadata. The example's
explicit result file is caller persistence; native node side effects still apply.
For typed transfer to another capability, read [handoffs](../handoffs.md).

## Files, repeated calls and concurrency

Persists the input, skill discovery, actions and final report in AnalysisRunStore keyed by request_id and storage. A completed matching request can resume its report. Preserve request identity for recovery; separate independent requests and stores.

## Errors and recovery

Inspect report status and certified references before reuse. Missing capability, unavailable assets or insufficient authorization is an environment limitation; do not replace measured findings with invented observations.

Input validation, missing task bindings, provider failures and scientific failure
are distinct outcomes. Retrying consumes the same resources and clock. Preserve
the actual error and input identity; do not broaden permissions or invent success.
