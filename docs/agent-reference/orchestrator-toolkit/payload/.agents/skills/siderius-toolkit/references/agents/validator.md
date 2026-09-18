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

Required fields name model_type, model/test/description paths, config_fields, model_description and mathematical_definition. Carry model_io_contract and candidate_id from implementation. Do not forward task prose through advice fields; follow the [context provenance rules](../treatment.md#preserve-context-provenance-when-building-requests). Provider configuration on inputs and constructor must use the run routing; field presence does not automatically configure a constructor.

For a saved `ImplementorOutput`, read and apply the
[restored-artifact handoff](../handoffs.md#restored-implementation-artifacts)
before building this input. Verifying or relocating files is caller glue; the
existing protocol owns the upstream-to-input field mapping.

### Configuration projection

When implementation output is available, preserve its `config_fields` through
the native handoff. For a standalone supplied candidate, this field contains
scalar parameter defaults (`int`, `float`, `bool`), not the complete plugin
config dump. For example, put `model_type="candidate_name"` in the dedicated
identity field and `{"hidden_dim": 16, "batch_size": 32}` in `config_fields`.
Do not copy the string `model_type` into that scalar mapping. If a genuine
parameter is non-scalar, report the interface limitation rather than silently
changing or dropping its semantics.

A caller-input error and a candidate-code error can occur in the same verdict.
Preserve both and correct only what is authorized; a corrected request is not
proof that the candidate passed. Inspect the returned status and diagnostics.

## Existing entrypoints and parameters

Python import: `nodes.ml_code_validator_agent.ml_code_validator_agent.MLCodeValidatorAgent`.
Native constructor at reference revision `1c68bc81`:

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

### Pytest cache placement

The native validator runs pytest in a child process. For supplied tests outside
the writable subtree, pytest can select a parent root and create `.pytest_cache`
there. Setting `StorageConfig` or the caller's working directory does not
confine this cache. If the run permits caller-managed process configuration,
set an absolute authorized cache path for this invocation before `node.run`:

```python
import os
import shlex
from pathlib import Path

cache_dir = Path(authorized_call_directory) / "pytest-cache"
cache_dir.mkdir(parents=True, exist_ok=True)
cache_option = "-o " + shlex.quote("cache_dir=" + str(cache_dir.resolve()))
os.environ["PYTEST_ADDOPTS"] = " ".join(
    part for part in (os.environ.get("PYTEST_ADDOPTS", ""), cache_option) if part
)
```

Use this in the isolated invocation process and preserve the run's existing
pytest options. This changes cache placement only; it does not authorize
changing tests, assertions or evaluation policy. If the environment fixes these
options, use its authorized configuration route instead. Check child-process
artifacts as well as native output paths when auditing write boundaries.

## Files, repeated calls and concurrency

Imports candidate plugins, runs pytest and structural/gradient checks, and may use model-assisted checks. The execution environment must already permit these effects. Process separation alone does not isolate shared registry/filesystem mutations.

### Skipped tests and acceptance evidence

At the reference revision, an empty `test_file_path`, a nonexistent path or a
path that is not a file makes the native pytest stage return `tests_passed=True`
with a `Skipped:` explanation. This supports an existing model-reuse path; the
boolean does not establish that tests executed or that this candidate is a
previously validated reusable model. The native schema accepts a missing path.

Read `test_output` and the actual artifact status before claiming tests passed.
For a new candidate whose task requires a supplied test suite, a missing suite
is missing acceptance evidence even if native booleans are true. Preserve the
native result unchanged and report the task-level gap separately. Do not create
replacement tests or borrow another candidate's result without authorization.
For legitimate reuse, follow the task's reuse policy and actual prior evidence;
this caveat does not impose a new universal testing requirement.

## Errors and recovery

Inspect passed and diagnostic fields. A schema-valid ValidatorOutput with passed=False cannot take the validated-model handoff. Repair using actual errors; never turn a failed validator into a successful training prerequisite.

Input validation, missing task bindings, provider failures and scientific failure
are distinct outcomes. Retrying consumes the same resources and clock. Preserve
the actual error and input identity; do not broaden permissions or invent success.
