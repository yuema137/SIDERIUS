# `implementor/`

Owns the implementor task-guidance adapter, not the implementor node's phase
orchestration. [`task_blocks.py`](task_blocks.py) loads an optional,
task-owned YAML mapping into `ImplementorTaskBlocks` from
[`agent.schemas.implementor`](../../schemas/implementor.py); omitted guidance
is an empty validated value and unknown keys fail closed.

There are no named prompt Markdown resources in this child. The shared loader
is [`../_task_blocks_loader.py`](../_task_blocks_loader.py), while the node
consumes the typed value at its input boundary. Keep this README out of prompt
content. Adapter behavior is exercised by
[`test_step12_pr12a_c7_implementor_blocks.py`](../../../../tests/unit/workflows/test_step12_pr12a_c7_implementor_blocks.py).
