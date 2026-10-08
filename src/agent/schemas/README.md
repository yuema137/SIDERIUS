# Typed messages between research steps

These schemas state what each research step accepts and returns. Validation
catches missing or malformed information before it reaches execution. Protocol
functions assemble one step's output into the next step's input; saved files
record what happened and do not replace that connection.

## Find the right part

| Need | Start here |
| --- | --- |
| Follow the connections | [Protocols](protocols/README.md) |
| Find the receiving step | [Node map](../../nodes/README.md) |
| Inspect usage records | [Telemetry](telemetry/README.md) |
| Extend a node | [Node contract template](../../nodes/NODE_TEMPLATE.md) |

## Technical detail

The [typed messages between research steps contract](schema-contract.md) records interfaces,
inputs, outputs, state changes, refusal behavior and related tests. Cross-package
rules remain with the mechanism references it links.
