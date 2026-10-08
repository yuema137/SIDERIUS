# SIDERIUS — entry point for coding agents

Read [CLAUDE.md](CLAUDE.md) first. It owns repository contribution policy;
the linked subsystem contracts and source own detailed behavior. This file
provides navigation, not a second set of rules.

SIDERIUS is a task-generic closed-loop research framework for supervised
scientific machine learning. Tasks supply scientific semantics through
composition manifests and plugins in external projects.

| Need | Start here |
| --- | --- |
| Contribution scope, planning, review and merge | [PR scope and structured-coding workflow](CLAUDE.md#pull-request-scope-and-structured-coding-workflow) |
| Environment binding and credentials | [Environment](CLAUDE.md#environment-and-launch-credentials) |
| Coding standards and subsystem owners | [Standards](CLAUDE.md#coding-standards), [single authorities](CLAUDE.md#architecture-and-single-authorities) |
| Documentation audiences and review | [Documentation rules](CLAUDE.md#documentation-audience-and-review) |
| Help a user configure their own task from a brief request | [Coding-agent setup route](README.md#start-with-your-coding-agent), [repository setup skill](docs/agent-reference/siderius-setup-review/SKILL.md) |
| Find a technical contract | [Reference index](docs/agent-reference/index.md) |
| Define a task | [Task composition](docs/reference/task-composition.md) |
| Understand the graph or add a node | [Architecture](docs/architecture.md), [node template](src/nodes/NODE_TEMPLATE.md) |

User task setup belongs in the user's external project. Repository contribution
work follows CLAUDE.md. Verify behavior from the selected source revision and
tests before claiming a capability or successful validation.
