# What SIDERIUS is

**Audience**: anyone deciding whether SIDERIUS is the right tool.
**Reading time**: ~5 minutes.

---

## The one-paragraph answer

SIDERIUS is a **closed-loop research framework for supervised scientific machine
learning**. You describe a scientific task — the data, what a model must read and
produce, what "better" means — and SIDERIUS runs the loop a research group would
run: read the evidence so far, propose a model architecture, implement it, check
that the implementation is sound, train and tune it, score it, judge whether the
result is trustworthy, interpret what happened, and go around again with what it
learned.

The parts that require judgement are performed by LLM agents. The parts that must
be exact — data selection, training, scoring, validity checking, provenance —
are deterministic code.

## What it is not

- **Not an AutoML library.** It does not search a fixed space of known models. It
  writes new model code each iteration and reasons about *why* the previous
  attempt behaved as it did.
- **Not a general agent framework.** The workflow is a fixed, deterministic path
  (`workflows/model_exploration.py` — "a workflow, not an orchestrator"), not an
  agent choosing its own tools. Agents occupy specific, typed positions in that
  path.
- **Not a benchmark harness.** It optimises one task at a time against that
  task's own declared metric; it does not maintain a leaderboard.
- **Not a hyperparameter sweeper.** Tuning is one phase inside a larger loop
  whose real output is an *architectural* line of enquiry.

## Why agents

An automated search can tell you *which* configuration scored best. It cannot
tell you *why* the previous architecture collapsed, or that a promising-looking
score came from a model emitting a near-constant signal. That reasoning —
reading diagnostic evidence, forming a hypothesis, deciding what to try next —
is what the agents do, and it is why the loop can change direction rather than
merely descend a gradient.

The framework's job is to make that reasoning *safe*: every agent output passes
through a Pydantic schema before it reaches execution, and no LLM ever decides
what data is read, how a result is scored, or whether a result is valid.

## The loop

![The SIDERIUS discovery loop](../assets/discovery-loop.svg)

Six LLM-powered stages. Everything inside the tune box that touches data — the
training run, the inference pass, the scoring, the health evaluation — is
deterministic. See [the iteration lifecycle](../guides/operating-a-run.md) for
what one round actually does.

## What "composable" means here

SIDERIUS separates **scientific semantics** (yours) from **execution
infrastructure** (its own).

![What you declare versus what SIDERIUS provides](../assets/ownership-split.svg)

A **task package** is that left-hand column, declared in one YAML manifest.
Composing a run binds those declarations for the whole run; nothing about your
task is hardcoded in framework source. Adding a task is authoring a manifest and
— where the framework has no suitable generic implementation — a small plugin.

See [What a task must provide](task-package.md).

## What it currently runs

SIDERIUS is contract-driven rather than modality-limited: support is decided by
whether a task can express itself through the framework's contracts, not by
whether its data shape appears on a list. Three example tasks exist as evidence
of tested breadth — a 1-D scientific signal task, an image classification task,
and a spatiotemporal regression task — at deliberately different and honestly
declared maturity.

Read [Supported tasks and current maturity](supported-tasks.md) before relying on
any of this. The differences between the three are real, and the document states
them plainly.

## Where the name comes from

Galileo's *Sidereus Nuncius* — the "starry messenger" — reported what a new
instrument revealed. SIDERIUS is aimed at the same thing: pointing an instrument
at noisy data and extracting the structure underneath.

---

## Next

- [Quickstart](../getting-started/installation.md) — install and verify
- [What a task must provide](task-package.md) — the core concept
- [Objectives, metrics and what "better" means](objectives-and-metrics.md)
- [Health gates](health-gates.md) — validity, as distinct from quality
- [Glossary](glossary.md)
