# `src/agent/schemas/protocols/`

Typed directed-edge adapters are the transport boundary between node schemas.
Each module owns one edge and exposes `local_*` (in-memory) and, where landed,
`database_*` transport functions. The registry and graph inventory are in
[`__init__.py`](__init__.py); concrete edge maps are the six `ml_*_to_ml_*.py`
modules listed there.

The graph fans in at validation→tuning (it consumes `ValidatorOutput` and
`ProposalOutput`) and literature-review→proposal (its four-channel values are
used directly by the workflow). Those sources remain the contract owners:
for example [proposal schemas](../proposal.py),
[validator schemas](../validator.py), and [storage](../storage.py); this
directory maps fields and does not duplicate their definitions. Mapping tests
live beside the node/workflow tests under [`tests/unit`](../../../../tests/unit/).
