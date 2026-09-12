# Prompt-template tests

Template owners live under [`src/agent/prompt_templates`](../../../../src/agent/prompt_templates/) and its task-block loader; node prompt contracts remain with node manuals. `test_proposal_prompts.py` checks evidence-backed causal/comparison rules, task-neutral wording, stage placeholders, available-loss ordering and formula substitution. The isolation and shape tests guard generic task fields. These are source-text assertions with stub registries; no LLM call occurs.

`.venv/bin/python -m pytest tests/unit/agent/prompt_templates/test_proposal_prompts.py -q`
