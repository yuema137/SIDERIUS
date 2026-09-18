---
name: siderius-toolkit
description: Discover and invoke the existing SIDERIUS scientific ML agents using their typed Python interfaces and documented CLI limits. Use when orchestrating the provided toolkit for a frozen research task, including selecting capabilities, preparing inputs, and passing outputs between calls.
---

# Use the existing SIDERIUS toolkit

Start from the workspace `AGENTS.md` and the operator-supplied `SIDERIUS-RUN.md`,
then read the task instructions it identifies. Resolve references relative
to this file. Read [invocation](references/invocation.md) before a first call,
and [artifact and concurrency rules](references/artifacts-and-concurrency.md)
before transferring results or overlapping calls.
For one operation, read its guide and schema first; read its CLI page only when
considering that CLI, and handoffs when transferring an output—including loading
a saved native output or relocating its artifact paths. Inspect source
for a specific unresolved question. A catalog review may require every guide;
an ordinary call does not require rereading the whole toolkit.

The supplied task package is frozen input. Preserve all of it, including task
instructions, manifests, schemas, plugins, budgets and access rules. Put caller
code, derived requests and outputs outside the infra installation and frozen
task package. The toolkit imposes no additional single-directory scratch or
cache restriction; preserve any locations required by the task itself.
Missing bindings are a setup question, not permission to rewrite the package;
use the [task binding guidance](references/invocation.md#task-binding).

Before each native invocation, apply the short
[request check](references/invocation.md#check-the-request-you-will-actually-send)
to the serialized request and save its outcome. Reading a task restriction does
not populate a schema field. Record an operation as started before the call,
then persist its outcome before planning the next one; the final summary is not
the only record of completed work.

This is a capability directory. Decide independently which applicable
capabilities to use, in what order, how often, with how many branches and when
to stop. No sequence or branch count is preferred. Optimize the task's valid
scientific result within its fixed budget; utilization is not a separate goal.

Use SIDERIUS agents for supported operations. Read
[capability selection](references/selection.md) before choosing custom scientific
logic or declaring an operation unsupported. A missing CLI flag does not imply
a missing Python capability. Distinguish capability gaps, missing prerequisites
and failed attempts; none changes the run's permissions or budget.

| Capability | Input → output | Read before using |
| --- | --- | --- |
| Literature review | typed research context and source configuration → findings, retrieved-paper references, vocabulary | [Literature review](references/agents/literature-review.md) |
| Data analysis, only when enabled | authorized assets, questions, access policy and envelope → measured findings and certified references | [Data analysis](references/agents/data-analysis.md) |
| Interpretation | typed run summaries or explicit cold start → structured interpretation and optional analysis brief | [Interpretation](references/agents/interpretation.md) |
| Proposal | typed interpretation and optional permitted evidence → model proposal and baseline configuration | [Proposer](references/agents/proposer.md) |
| Implementation | model proposal and task contract → model/loss code, tests and artifact descriptors | [Implementer](references/agents/implementer.md) |
| Code validation | generated candidate and I/O contract → validation verdict and diagnostic evidence | [Validator](references/agents/validator.md) |
| Tuning and evaluation | validated candidate, task bindings and resource configuration → training/evaluation records and selected results | [Tuner](references/agents/tuner.md) |

Each guide links the complete top-level input/output field inventory and the
existing constructor/CLI options. Nested schema structure is discoverable from
the native classes using the inspection examples. Never invent an argument,
assume a CLI accepts the full Python input, or substitute a generic API default
for a frozen experiment value. Prefer existing typed protocols for handoffs;
the [handoff map](references/handoffs.md) describes their actual projections.

Read [evidence and enablement boundaries](references/treatment.md) before
populating advice or optional evidence fields. Task prose, human advice and
native upstream guidance have different sources; a permissive string field is
not permission to exchange them. Interface documentation is not human scientific advice.
A listed Data Analysis interface grants no access when disabled. Advice and
measured findings are separately authorized artifacts, never bundled into this
generic skill.

Record actual requests, responses, parent artifacts and observable costs in the
run's existing record locations. Preserve native status, identity, validity and
metric fields. Documentation adds no enforcement layer: use only the provided
authorized execution environment, and report missing permissions or unsupported
bindings without weakening the common task contract.
