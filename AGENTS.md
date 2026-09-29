# SIDERIUS — entry point for coding agents

**Read [`CLAUDE.md`](CLAUDE.md) first.** It is the single authority for this
repository's coding standards, subsystem invariants and current state.

This file used to carry its own copy of those rules. The copy drifted — it kept
saying SIDERIUS was a TIDMAD denoising project long after the framework became
task-generic — so it is now a pointer rather than a second authority. If you are
looking for a rule and it is not in `CLAUDE.md`, it is not a rule.

---

## What SIDERIUS is, in three sentences

A closed-loop research framework for supervised scientific machine learning. An
LLM agent loop — interpret → propose → implement → validate → tune — surrounds a
deterministic execution core that owns data selection, training, scoring, validity
checking and provenance. A scientific task declares its own semantics through a
**task composition manifest** and plugins; nothing about a task is hardcoded in
framework source.

## Where to go

| you need | go to |
|---|---|
| the rules you must follow | [`CLAUDE.md`](CLAUDE.md) |
| README/tutorial readability and other Markdown contracts | [`Documentation audience and review`](CLAUDE.md#documentation-audience-and-review) |
| to find the right technical doc for a task | [`docs/agent-reference/README.md`](docs/agent-reference/README.md) |
| what a user must declare | [`docs/reference/task-composition.md`](docs/reference/task-composition.md) |
| what is landed vs planned | [`docs/concepts/supported-tasks.md`](docs/concepts/supported-tasks.md) |
| the system's shape | [`docs/architecture.md`](docs/architecture.md) |
| to add a node | [`nodes/NODE_TEMPLATE.md`](src/nodes/NODE_TEMPLATE.md) |
| why something is the way it is | [`docs/design/README.md`](docs/design/README.md) — history, not current behaviour |

## Environment, in one line

Run `uv sync --group dev --frozen` in the exact checkout, then use its
`.venv/bin/python` for tests and campaigns. Never reuse another checkout's
virtualenv, editable install, `site-packages`, or source through `PYTHONPATH`;
the full binding rule lives in [`CLAUDE.md`](CLAUDE.md).

## Four things that are enforced, not aspirational

1. **Pydantic at every boundary.** LLM output → schema → execution. Execution
   reads the validated object, never a raw dict.
2. **Nodes communicate only through schemas, protocols and their own storage.**
   Storage is a log, not a channel.
3. **One LLM gateway** (`agent/llm_bridge`). Direct provider constructors
   elsewhere are CI-banned.
4. **One authority per rule.** Metric direction has exactly one interpreter;
   deliverable naming has one owner. Re-inlining any of them is precisely the
   defect the guards exist to catch.

## Before you claim something is current

A design document is evidence of **intent**. Landed source and its tests are
evidence of **capability**. Verify status from git — branch ancestry and changed
paths — not from a roadmap row or a document header.
