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
[evidence integrity checks](INTEGRITY-QUALIFICATION.md), for evidence and
its limits. Original native interface inventory:
`1c68bc81d7e44bbdc6e03a445a8422c3f77f45ff`. The payload field and CLI
tables were reconciled against `0b44e40505b99fd752526c1ff9e9fc97c219dde2`
(v0.2.9) for the O-Full deployment qualification; the original source labels
remain provenance, not a runtime version requirement.

Compatibility check at v0.2.9: the 14 documented input/output tables have
exact top-level Pydantic field-name parity with the installed classes. The
tuner CLI page lists all 65 primary long options, including the two newly
added options, and its documented step/batch defaults match `build_parser()`.
The other five CLI parser files did not change between the original inventory
and v0.2.9. Nested structures and runtime cross-field rules still require
inspection of the installed schemas before constructing a request.
