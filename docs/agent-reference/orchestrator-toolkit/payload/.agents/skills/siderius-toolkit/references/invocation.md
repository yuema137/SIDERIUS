# Calling an existing agent

Use the exact SIDERIUS environment and paths declared by the operator in the
workspace `SIDERIUS-RUN.md`. It must identify the approved revision, task
instructions, authorized executor route, storage, model routing and active information
treatment. Do not borrow a different checkout's Python or add its source through
`PYTHONPATH`. Package availability does not give a research agent read access to
evaluator-only data, scorer internals, credentials or other runs.

## Finding installed source

The Python names below are import paths, not paths relative to a checkout root.
In the source checkout, `agent`, `nodes` and `workflows` live under `src/`.
For an installed package, import the documented class using the declared Python
and inspect its source with `inspect.getfile(TheImportedClass)`, after binding
the generated library as required. Some node packages expose compatibility
aliases, so `find_spec` on a dotted node module can fail even when the documented
class import works. Inspect that installation; a missing root-level `agent/`
directory does not mean the API is absent.

Preserve the infra installation/source and the complete frozen task package,
including their configuration and dependency files. Put generated libraries,
caller scripts, reports, temporary files and caches outside these protected
roots. Other scratch locations are not restricted by this toolkit; follow any
existing task/environment requirements. Redirect helper caches when their
default would write into a protected root. A request check does not require
running the framework test suite.

## Native Python boundary

The interfaces in this skill are existing Python classes with `run(input)`.
There is no universal `siderius invoke --input-json` command at this revision.
Use the per-agent guide for the precise class and constructor; constructors and
inputs have different model-routing fields.

This example demonstrates input validation only; it makes no provider call:

```python
from pathlib import Path
from agent.schemas.proposal import ProposalInput

# A caller-owned request assembled from authorized evidence and frozen values.
request = ProposalInput.model_validate_json(Path("proposal-input.json").read_text())
print(request.model_dump_json(indent=2))
```

The schema rejects malformed values, but a valid schema can still omit
experiment-required context or contain a source default inappropriate to this
run. Before execution compare the actual input with the common task and frozen
run descriptor. Do not use `model_construct` to bypass validation. If modifying
an already validated input, reconstruct through `model_validate`; unvalidated
`model_copy(update=...)` is not a substitute for that boundary.

### Check the request you will actually send

Use the validated, serialized input for this check, not the prose you intended
to send. Record the checked values and their source paths beside that request:

| Check | What to compare |
| --- | --- |
| Task contract | The recipient's actual I/O contract and task fields against the frozen declarations. |
| Restricted data scope, when the recipient has it | Resolve its actual `DataScope` using the declared partition count and compare with the authorized indices. A null field is the whole dataset even when `constraints` names a subset. See [scope and handoffs](#structured-scope-and-handoffs). |
| Advice provenance | For each nonempty advice field, identify the exact authorized upstream artifact or human-advice source. Your own implementation instructions stay in caller context. See [context provenance](treatment.md#preserve-context-provenance-when-building-requests). |

Resolve a mismatch in caller-owned request construction, preserving the frozen
package. Do not launch the mismatched request and defer correction until tuning.
If a recipient lacks a field, report that boundary instead of inventing it or
relabelling context as advice.

Persist a `started` record immediately before the call. As soon as it returns or
is interrupted, save the actual output/error/interruption and update the run's
readiness before planning another call. A successfully written initial readiness
file is not an up-to-date record. If interruption prevents a final update, the
started record must remain distinguishable from success or never attempted.
When the run requests both machine-readable status and a human-readable report,
create compact initial versions once the task and writable paths are known, then
update them after meaningful preparation or execution outcomes; do not defer one entirely
to a final turn that may be interrupted.

Each capability page includes a function showing a **single native invocation**
with its dependencies passed explicitly. These functions are documentation
examples, not installed wrapper functions, a scheduler, an RPC server, or a
complete main-experiment launch. The operator's execution route must already
provide the required permissions, input artifacts and task bindings.

## Task binding

When the existing API needs composed task state, the supported binding helpers
are `workflows.task_composition.compose_run_task_bindings(manifest_path)` and
`bind_run_task_composition(composition, physical_data_root=...)`.
`build_task_composition_ref(composition)` returns the native projection carried
by node inputs. It does not itself establish the ambient binding.

In a provisioned executor, a single call can use this existing pattern:

```python
from workflows.task_composition import (
    bind_run_task_composition,
    build_task_composition_ref,
    compose_run_task_bindings,
)

def in_task_context(manifest_path, authorized_data_root, invoke):
    composition = compose_run_task_bindings(manifest_path)
    with bind_run_task_composition(composition, physical_data_root=str(authorized_data_root)):
        return invoke(composition, build_task_composition_ref(composition))
```

### Complete bootstrap for a fresh root caller

The short helper above assumes an executor already initialized the process.
For a **fresh root caller**, use the following complete ordering. Save your
caller in the external project; do not import nodes, plugin registries or task
composition helpers above the generated-library binding. Run descendants through
their existing transport; do not use `root_code_scope` to erase an inherited pin
inside a worker.

```python
def run_native_call(manifest_path, data_root, output_directory, invoke):
    from pathlib import Path
    from core.generated_library import bind_generated_library_to_workspace

    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=False)
    bind_generated_library_to_workspace(str(output))

    from core.durable_io import publish_bytes_write_once
    from core.local_code import root_code_scope

    with root_code_scope():
        from workflows.task_composition import (
            bind_run_task_composition,
            build_task_composition_ref,
            compose_run_task_bindings,
        )

        composition = compose_run_task_bindings(str(Path(manifest_path).resolve()))
        with bind_run_task_composition(composition, physical_data_root=str(Path(data_root).resolve())):
            reference = build_task_composition_ref(composition)
            # The callback imports the chosen node, constructs its native input,
            # configures its workspace/storage and returns its typed output.
            result = invoke(composition, reference, output)
            publish_bytes_write_once(
                str(output / "capability-output.json"),
                result.model_dump_json(indent=2).encode("utf-8"),
            )
            return result
```

Pass your own callback and explicit manifest/data/output paths. The callback
still owns node-specific typed inputs, measurement capability where required,
model routing and native storage; the output directory alone does not configure
every node's storage. The helper refuses to reuse a result directory. A failure
may leave that directory without `capability-output.json`; preserve the error
and partial artifacts instead of treating directory existence as success.
This helper is an example, not an installed scheduler or provider wrapper.

The callback still has to populate the specific node's typed input. Composition
does not automatically inject all task prose, I/O contracts, advice, hardware,
Health or protocol fields. The per-agent guide identifies those inputs.
Composition imports task plugins and can require evaluator-owned modules; an
agent-visible sanitized task view is not necessarily executable by itself.
Do not recover missing private files by exposing the evaluator tree to the
research agent. An authorized executor must supply the existing operation; if
none is provisioned, report that capability unavailable in this environment.

### Restore persisted composition references before execution

A JSON round trip does not restore every runtime type in `TaskCompositionRef`.
Some dependency-neutral fields are typed `Any`: for example, the Health absence
state becomes the string `explicit_none`, and an objective can become a plain
mapping. `model_validate_json` alone does not rebuild these objects. The native
Health consumer expects the absence enum and otherwise treats a string as a
configuration path. Schema acceptance is therefore not execution readiness.

For a persisted node request, rebuild the reference from the same authorized,
frozen manifest through the existing composition helper, compare the entire
serialized projection with the saved one, then supply the native reference
**before** validating and executing the recipient input:

```python
import json
from pathlib import Path
from agent.schemas.hyperparam_tuning import HyperparamTuningInput, TaskCompositionRef
from workflows.task_composition import build_task_composition_ref


def restore_tuner_request(request_path, composition):
    payload = json.loads(Path(request_path).read_text())
    native_ref = build_task_composition_ref(composition)
    if native_ref is None or payload.get("task_composition_ref") is None:
        raise ValueError("Expected the persisted composed-task identity")
    saved_ref = TaskCompositionRef.model_validate(payload["task_composition_ref"])
    if saved_ref.model_dump(mode="json") != native_ref.model_dump(mode="json"):
        raise ValueError("Persisted task composition differs from the frozen binding")
    payload["task_composition_ref"] = native_ref
    return HyperparamTuningInput.model_validate(payload)
```

Call this inside the declared task context above. The same reconstruction rule
applies to other recipient inputs carrying this reference; use their own native
input class. Preserve the reconstructed request object through `node.run()`;
serializing it for provenance does not mean passing the serialization back into
execution. A changed projection is a recovery error, not permission to overwrite
its fingerprint or alter the task. Do not create a file named `explicit_none`,
change Health settings, or expose private modules to make a failed restore run.
If the authorized composition cannot be loaded in this executor, report that
missing deployment prerequisite.

### Standalone operations with a public dataset profile

Some standalone preparation operations need the dataset profile without needing
a scorer or a complete composed execution context. If the frozen manifest
references a public resolved profile, use its exact file through the existing
API; resolve the path relative to that manifest, not to the caller's cwd:

```python
from execute_tools.dataset_config import load_dataset_profile, bind_dataset_profile


def with_declared_profile(resolved_profile_path, invoke):
    profile = load_dataset_profile(str(resolved_profile_path))
    with bind_dataset_profile(profile):
        return invoke()
```

This establishes only the profile dependency. It does not bind scoring, data
access, Health, metrics or the full task composition. Keep the context around
input construction and the call that needs it; bind explicitly in each worker
rather than assuming context crosses subprocess boundaries. Supply the node's
other declared inputs from the frozen task. Never replace a missing profile
with a shipped example or create a reduced manifest to bypass missing plugins.
If a later required binding is unavailable, save the native error and report
that prerequisite; successful profile loading is not proof the call can finish.

### Structured scope and handoffs

Read the permitted partition scope from the frozen task and run declaration.
Where a native input or protocol accepts `DataScope`, carry that scope explicitly
and inspect the persisted request. `file_indices=None` means the complete
dataset, not a textual band, the files currently mounted, or the last call's
scope. Resolve against the declared profile's partition count; do not hardcode
a dataset size or infer access from a directory listing.

Use the run declaration's resolved scope and cited task authority together.
Do not reinterpret a selected band as all partitions merely because the profile
lists the whole dataset. If the label-to-index mapping is unavailable, record
that missing binding; a null default is not a substitute for resolving it.

A native protocol maps its documented fields, not every restriction in the run.
After each handoff or restored output, retain the original run scope and supply
it again where the recipient requires it. Do not invent `data_scope` fields on
schemas that do not have one. An upstream proposal is not a grant of broader
access. If task and run declarations conflict or omit a required restriction,
record the ambiguity before data execution; do not amend the frozen package.

## Task prose and forward contract

Inside the existing bound task context, use the task-config loader:

```python
from workflows.task_config import load_task_config, get_task_description
from agent.schemas.task_config import ForwardContract


def task_prompt_context():
    config = load_task_config()
    description = get_task_description(config)
    contract = ForwardContract.model_validate(config["forward_contract"])
    return description, contract
```

This helper returns caller context, not a new task declaration. Pass
`task_description` to the recipient and `forward_contract` where its input
schema declares it. In particular, ImplementorInput takes `forward_contract`;
ImplementorOutput carries the realized `model_io_contract` to ValidatorInput.
Do not guess that similarly named schemas accept the same field names.
`bind_run_task_composition` requires a real physical data root, even for a
composed call whose immediate reasoning stage does not train. Passing `None`
is refused. Pass the existing directory as a string; this helper does not accept
a `Path` object for `physical_data_root`. Prepare the authorized task's data
through its existing route.

## Configuration and observations

Arguments documented as generic defaults are not new experiment choices.
The operator supplies fixed per-role provider/model/effort values separately
from human advice. A standalone CLI may omit effort or richer fields that the
Python API supports. Read its limitations before substituting it.

Use native token and run-context recording where provided. Most reasoning
nodes expose their existing `bridge.set_run_context(...)`; the tuner has
`set_run_context(...)` before its lazy bridge is created. Literature and Data
Analysis construct bridges during execution. For a node exposing `bridge`, the
existing recording call has exactly these keyword arguments:

```python
from pathlib import Path

# record_workspace is outside the protected infra and task roots.
# The bridge binds an existing directory; it does not create this directory.
record_path = Path(record_workspace)
record_path.mkdir(parents=True, exist_ok=True)
node.bridge.set_run_context(
    workspace=record_path,
    iter=iteration,
    run_name=run_name,
    run_id=run_id,
)
```

For the tuner, call `node.set_run_context(...)` with those same four keywords.
The bridge requires an existing writable directory, a non-negative `iter`, and
an unchanged `run_id` once bound. On that bridge, later `iter` values cannot go
backwards. These are recording preconditions, not new scientific run budgets.
Neither method accepts `node_name`; do not infer arguments from a method name
or from `hasattr`. Recording context configures accounting, not task binding.
Do not claim complete token
accounting from merely calling `run`; preserve actual CLI/provider receipts and
report missing observations. These documents add no new instrumentation.

Read native outputs through their Pydantic classes. Record errors from
validation, task binding, provider calls and execution separately; do not turn a
failed call into a successful scientific result or grant a fresh unit budget.
