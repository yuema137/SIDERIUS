# literature-review: one existing capability

## Capability and prerequisites

Retrieve and synthesize literature into typed findings. This does not train or score a candidate.

Before calling, read [shared invocation](../invocation.md),
[artifact/concurrency effects](../artifacts-and-concurrency.md), and the
[native input/output field inventory](../schemas/literature-review.md). The inventory lists
required fields, optional fields, types, generic defaults and constraints;
its native-schema inspection shows all nested models. Custom validation remains
authoritative. Schema descriptions can retain historical examples: the active
task contract, not an example or fallback, supplies scientific semantics.

Supply typed interpretation evidence, task description, storage and run name; select root papers, dynamic search, synthesis and confidence configuration from authorized sources. Provider/model/effort and search routing live on the input. The constructor requires an explicit root_cache_dir.

## Existing entrypoints and parameters

Python import: `nodes.ml_literature_review.ml_literature_review.MLLiteratureReviewAgent`.
Native constructor at reference revision `2df46e22`:

```text
MLLiteratureReviewAgent(bridge_factory=None, *, root_cache_dir: str)
```

`bridge_factory` is existing dependency injection, not a model-provider choice.
Use production defaults unless the declared execution environment supplies one.
Frozen routing/limits/access policy belong to the run descriptor. The orchestrator
may choose only parameters left open there; schema defaults do not override it.

[CLI flags](../cli/literature-review.md)

The standalone CLI requires a task composition and physical data root even though this node does not train. Its YAML enabled switch gates the fixed workflow only; invoking the CLI itself executes the node. Check run enablement before invoking.

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
from agent.schemas.literature_review import LiteratureReviewInput, LiteratureReviewOutput
from nodes.ml_literature_review.ml_literature_review import MLLiteratureReviewAgent


def invoke(request_path, result_path, *, root_cache_dir):
    request = LiteratureReviewInput.model_validate_json(Path(request_path).read_text())
    node = MLLiteratureReviewAgent(root_cache_dir=root_cache_dir)
    result = node.run(request)
    if not isinstance(result, LiteratureReviewOutput):
        raise TypeError("Unexpected native output type")
    Path(result_path).write_text(result.model_dump_json(indent=2))
    return result
```

Expected output is `LiteratureReviewOutput`, not an unvalidated dictionary. See its field table
for exact shape, required fields and status/diagnostic metadata. The example's
explicit result file is caller persistence; native node side effects still apply.
For typed transfer to another capability, read [handoffs](../handoffs.md).

## Files, repeated calls and concurrency

Reads permitted paper sources and writes cache entries and review records. Give overlapping calls independent cache destinations unless the existing cache owner provides suitable coordination. Preserve paper identities and confidence evidence.

## Errors and recovery

A retrieval failure, abstract-only source or empty findings set is not evidence that a scientific claim is false. Preserve verbosity and confidence metadata; use the actual output projection for downstream context.

Input validation, missing task bindings, provider failures and scientific failure
are distinct outcomes. Retrying consumes the same resources and clock. Preserve
the actual error and input identity; do not broaden permissions or invent success.
