# Select an existing capability before replacing it

The catalog is the first place to locate an operation. For a matching capability,
read its guide and native input/output inventory before choosing how to invoke
it. Use the provided SIDERIUS agent when it supports the operation and the run
authorizes it. The caller still chooses order, count, branches and concurrency.

## Distinguish the reason an invocation cannot proceed

| Situation | Next action within the current task |
| --- | --- |
| Native API expresses the required operation | Assemble a validated input and call that agent; do not replace its scientific reasoning/checks with a handwritten equivalent |
| CLI does not carry needed context | Check the documented Python API and typed protocols before declaring a gap |
| An input, task binding or executable capability is missing | Identify the missing prerequisite; use its authorized preparation route if supplied, otherwise report it unavailable |
| The capability is disabled or access is prohibited | Preserve the restriction; a custom implementation is not a way to re-enable it |
| A provider, validation or execution attempt fails | Preserve the actual error and inspect supported recovery; one failed attempt does not prove the toolkit lacks the operation |
| No available capability expresses a required operation | State the examined interface and specific missing behavior; permitted custom code may implement that gap without duplicating supported operations |

A source search can resolve a documentation ambiguity. Read the documented
surface first and use the pinned source to verify it; do not infer support from
a class name or accept an old handoff note as newer than the installed schema.

## Caller code and evidence

Python request builders, task-binding contexts, native protocol calls, result
serialization and a requested report-format conversion are caller glue. They
are often necessary because the toolkit exposes typed Python APIs. They do not
require a claim that the underlying agent is unsupported.

By contrast, implementing your own model proposal, candidate implementation,
code-validation engine, analysis algorithm or tuning loop in place of an enabled
matching agent needs a concrete capability gap. Convenience, familiarity, or a
shorter script does not establish that gap. Preserve the existing scientific
input/output and task constraints when implementing a permitted missing part.

Record the selected native entrypoint and actual request/output artifact in the
ordinary run record. If a custom operation is necessary, briefly identify its
missing behavior and the relevant interface inspected. Keep this explanation
proportional; it is not an extra approval step and does not prescribe a pipeline.

The operator can inspect actual file reads and native call artifacts. A statement
that the toolkit was read is not by itself evidence of either comprehension or
use. On recovery, reopen the entry, run declaration and relevant references
before applying a stale plan; validate persisted native outputs before reuse.
