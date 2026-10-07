# Existing interface boundaries

Reference: SIDERIUS `1c68bc81d7e44bbdc6e03a445a8422c3f77f45ff`.
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
| Measurement | Native node/provider receipts where available; documentation adds no universal accounting or enforcement |
| Scientific contract | External task owns data selection, metric, Health, eligibility and deliverables; native defaults are not experiment requirements |

Source field descriptions can contain historical examples and legacy defaults.
The task's declared contract and runtime validators are authoritative. Generic
interface documentation must not promote those examples into a scientific rule.

The caller can use an existing API where the CLI lacks required context. If the
API cannot express an operation or the environment lacks execution permission,
record the limitation. Do not patch the framework or bypass task restrictions
under the guise of invoking this documentation wrapper.
