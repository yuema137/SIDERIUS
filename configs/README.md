# Framework configuration

This directory contains framework policy, provider/model routing and manifests
for synthetic examples. A real scientific task keeps its declarations in its
own package. Choose the configuration by the decision you want to change,
then check which launcher reads it.

## Find the right part

| Need | Start here |
| --- | --- |
| Choose providers and models | [LLM routing](llm/README.md) |
| Choose Health consequences | [Health policy](health/README.md) |
| Inspect resource profiles | [Runtime profiles](runtime/README.md) |
| Try a synthetic task | [Example manifests](task_composition/README.md) |
| Find configuration ownership | [Configuration reference](../docs/reference/configuration-map.md) |

## Technical detail

The [framework configuration contract](configuration-contract.md) records interfaces,
inputs, outputs, state changes, refusal behavior and related tests. Cross-package
rules remain with the mechanism references it links.
