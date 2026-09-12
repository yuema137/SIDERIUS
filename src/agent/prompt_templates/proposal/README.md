# `proposal/`

Owns the proposer stage resources and task-guidance adapter. The three stages
(`causal_reasoning`, `comparison`, and `proposing`) each have explore and
exploit resources; for example, [`causal_reasoning_stage_explore.md`](causal_reasoning_stage_explore.md)
and its [`_exploit`](causal_reasoning_stage_exploit.md) sibling. The complete
set is visible in this directory; these named files are selected by proposal
rendering and `README.md` is not prompt content.

[`task_blocks.py`](task_blocks.py) validates task-owned prose as
`ProposalTaskBlocks` from [`agent.schemas.proposal`](../../schemas/proposal.py).
It is separate from implementor blocks even though both use
[`../_task_blocks_loader.py`](../_task_blocks_loader.py). Prompt behavior is
covered by [`test_step00_prompt_goldens.py`](../../../../tests/unit/agent/ml_model_proposal_agent/test_step00_prompt_goldens.py)
and the adapter by [`test_step12_pr12a_c7_proposal_blocks.py`](../../../../tests/unit/workflows/test_step12_pr12a_c7_proposal_blocks.py).
