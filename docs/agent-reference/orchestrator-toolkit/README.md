# SIDERIUS orchestrator toolkit documentation

A coding agent can discover and call the existing SIDERIUS capabilities through
this layered documentation. The agent chooses call order, repetitions, branching
and concurrency within the supplied task's constraints.

Start with [assembly](ASSEMBLY.md), then review the [interface limitations](COMPATIBILITY.md).
The distributable instructions are under [payload/](payload/AGENTS.md); operator
pages outside payload are not research-agent inputs. This package adds Markdown
only. It implements no agents, scheduler, launchers, schemas or execution service.

The operator supplies the scientific task, authorized environment and run
constraints. This generic toolkit defines no dataset, experiment arm, training
fraction, metric direction, retrieval policy or model routing. It can be added
to an existing task package without changing that package's files.

See the [initial verification](VERIFICATION.md) and subsequent
[discovery qualification](QUALIFICATION.md), plus the
[multi-task checks](MULTITASK-QUALIFICATION.md) and
[evidence integrity checks](INTEGRITY-QUALIFICATION.md), for evidence and its limits. Native interface
reference revision: `1c68bc81d7e44bbdc6e03a445a8422c3f77f45ff`.
