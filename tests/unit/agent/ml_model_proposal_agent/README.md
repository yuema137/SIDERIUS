# Model-proposal node tests

The source owner is [`ml_model_proposal_agent.py`](../../../../src/nodes/ml_model_proposal_agent/ml_model_proposal_agent.py); proposal contracts and evidence are owned by `agent.schemas.proposal` and `proposer_evidence`. `test_agent_cards.py` verifies card field limits, trust-vocabulary validation, dict/model intake, deterministic rendering, guidance ordering, and citation deduplication/sorting. The wider family uses mocked prompts and synthetic health/hardware evidence to test applicability, causal stages, truncation and provenance—not scientific proposal quality. `goldens/` contains preserved prompt payloads.

`.venv/bin/python -m pytest tests/unit/agent/ml_model_proposal_agent/test_agent_cards.py -q`
