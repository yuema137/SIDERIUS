# Calling an existing agent

Use the exact SIDERIUS environment and paths declared by the operator in the
workspace `SIDERIUS-RUN.md`. It must identify the approved revision, task
instructions, authorized executor route, storage, model routing and active information
treatment. Do not borrow a different checkout's Python or add its source through
`PYTHONPATH`. Package availability does not give a research agent read access to
evaluator-only data, scorer internals, credentials or other runs.

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
    with bind_run_task_composition(composition, physical_data_root=authorized_data_root):
        return invoke(composition, build_task_composition_ref(composition))
```

The callback still has to populate the specific node's typed input. Composition
does not automatically inject all task prose, I/O contracts, advice, hardware,
Health or protocol fields. The per-agent guide identifies those inputs.
Composition imports task plugins and can require evaluator-owned modules; an
agent-visible sanitized task view is not necessarily executable by itself.
Do not recover missing private files by exposing the evaluator tree to the
research agent. An authorized executor must supply the existing operation; if
none is provisioned, report that capability unavailable in this environment.

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
is refused. Prepare the authorized task's data through its existing route.

## Configuration and observations

Arguments documented as generic defaults are not new experiment choices.
The operator supplies fixed per-role provider/model/effort values separately
from human advice. A standalone CLI may omit effort or richer fields that the
Python API supports. Read its limitations before substituting it.

Use native token and run-context recording where provided. Most reasoning
nodes expose their existing `bridge.set_run_context(...)`; the tuner has
`set_run_context(...)` before its lazy bridge is created. Literature and Data
Analysis construct bridges during execution. Do not claim complete token
accounting from merely calling `run`; preserve actual CLI/provider receipts and
report missing observations. These documents add no new instrumentation.

Read native outputs through their Pydantic classes. Record errors from
validation, task binding, provider calls and execution separately; do not turn a
failed call into a successful scientific result or grant a fresh unit budget.
