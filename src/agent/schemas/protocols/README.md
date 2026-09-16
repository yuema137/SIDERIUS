# `src/agent/schemas/protocols/`

Typed directed-edge adapters are the transport boundary between node schemas.
Each module owns one edge and exposes `local_*` (in-memory) and, where landed,
`database_*` transport functions. The registry and graph inventory are in
[`__init__.py`](__init__.py); each concrete module names one producer-to-consumer
edge.

The graph fans in at validation→tuning (it consumes `ValidatorOutput` and
`ProposalOutput`) and at Proposal, which receives Interpretation, Literature
Review and Data Analysis as separate target-owned typed projections. The
workflow may also connect Literature Review and Data Analysis in either order;
neither node imports or invokes the other. Those sources remain the contract owners:
for example [proposal schemas](../proposal.py),
[validator schemas](../validator.py), and [storage](../storage.py); this
directory maps fields and does not duplicate their definitions. Mapping tests
live beside the node/workflow tests under [`tests/unit`](../../../../tests/unit/).
