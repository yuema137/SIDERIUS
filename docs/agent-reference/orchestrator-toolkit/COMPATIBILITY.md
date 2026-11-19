# Existing interface boundaries

Reference: SIDERIUS `1c68bc81d7e44bbdc6e03a445a8422c3f77f45ff`; the Model routing
and Measurement rows were re-verified at `5ccb436f` (v1.1.0). The payload's
schema field tables, CLI option tables and constructor signatures are generated
from the installed code by `python -m tools.orchestration_setup.reference_tables`
and checked by `tests/unit/tools/test_orchestration_reference_tables.py`, so they
match the checkout that ships them. Nested structures and runtime cross-field
rules still require inspection of the installed schemas.
This page describes capability, not qualification of any scientific experiment.

| Surface | Supported boundary or limitation |
| --- | --- |
| Python nodes | Seven existing typed `run(input)` interfaces; input validation is necessary but does not supply missing task context |
| Standalone CLI | Six existing CLIs, with different field coverage; Data Analysis has none |
| Task composition | Existing compose/bind helpers; a projection on an input does not establish ambient task binding |
| Execution access | An authorized executor and task dependencies must already exist; sanitized public task files may omit required private plugins |
| Data Analysis | Requires a real task analysis capability plus authorized inputs; cannot be activated by supplying a JSON stub |
| Persistence | Local storage and typed local protocols; database protocol alternatives remain placeholders |
| Parallel calls | Caller-controlled scheduling, with real shared filesystem/registry/process/GPU conflicts to account for; no blanket safety guarantee |
| Model routing | Different constructor/input locations by node; proposer honors stage overrides through its public routing contract; legacy two-call mode uses reasoning routing |
| Measurement | Native node/provider receipts where available; run-context binding differs by node: the proposer and tuner bind through their own `set_run_context`, Interpretation, Implementer and Validator through their eager `bridge`, and Literature review and Data Analysis through `contextual_bridge_factory`; documentation adds no universal accounting or enforcement |
| Scientific contract | External task owns data selection, metric, Health, eligibility and deliverables; native defaults are not experiment requirements |

Source field descriptions can contain historical examples and legacy defaults.
The task's declared contract and runtime validators are authoritative. Generic
interface documentation must not promote those examples into a scientific rule.

The caller can use an existing API where the CLI lacks required context. If the
API cannot express an operation or the environment lacks execution permission,
record the limitation. Do not patch the framework or bypass task restrictions
under the guise of invoking this documentation wrapper.
