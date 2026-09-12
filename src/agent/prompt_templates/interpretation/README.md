# `interpretation/`

Owns interpretation prompt assembly and task-guidance loading. The phase
renderer is [`rendering.py`](rendering.py); it imports schemas and framework
authorities and is called by the node, never the reverse. The adapter in
[`task_blocks.py`](task_blocks.py) validates the task-owned mapping as
`InterpretationTaskBlocks` from [`agent.schemas.interpretation`](../../schemas/interpretation.py).

The four section names and their render placement are owned by the renderer;
this README is not prompt content. The shared mechanics are in
[`../_task_blocks_loader.py`](../_task_blocks_loader.py). Validate prompt
parity with [`test_step00_prompt_goldens.py`](../../../../tests/unit/agent/result_interpretation_agent/test_step00_prompt_goldens.py)
and task blocks with [`test_step09b_interpretation_prompts.py`](../../../../tests/integration/nodes/test_step09b_interpretation_prompts.py).
