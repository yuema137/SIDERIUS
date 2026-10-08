# Agent support

This package provides the shared parts used by research agents: typed messages,
prompt rendering, callable tools and the single LLM gateway. The research
steps themselves live in the neighboring nodes package. Start with the part
that matches the behavior you are changing.

## Find the right part

| Need | Start here |
| --- | --- |
| Find a research step | [Nodes](../nodes/README.md) |
| Understand messages between steps | [Schemas and protocols](schemas/README.md) |
| Inspect prompt assembly | [Prompt resources](prompt_templates/README.md) |
| Find a callable tool | [Skills](skills/README.md) |

## Technical detail

The [agent support contract](agent-contract.md) records interfaces,
inputs, outputs, state changes, refusal behavior and related tests. Cross-package
rules remain with the mechanism references it links.
