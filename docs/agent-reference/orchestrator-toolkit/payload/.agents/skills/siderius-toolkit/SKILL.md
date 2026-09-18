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

This is a capability directory. Decide independently which applicable
capabilities to use, in what order, how often, with how many branches and when
to stop. No sequence or branch count is preferred. Optimize the task's valid
scientific result within its fixed budget; utilization is not a separate goal.

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

Read [evidence and enablement boundaries](references/treatment.md) when selecting
context for a request. Interface documentation is not human scientific advice.
A listed Data Analysis interface grants no access when disabled. Advice and
measured findings are separately authorized artifacts, never bundled into this
generic skill.

Record actual requests, responses, parent artifacts and observable costs in the
run's existing record locations. Preserve native status, identity, validity and
metric fields. Documentation adds no enforcement layer: use only the provided
authorized execution environment, and report missing permissions or unsupported
bindings without weakening the common task contract.
