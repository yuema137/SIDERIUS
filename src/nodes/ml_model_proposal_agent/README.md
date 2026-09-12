# src/nodes/ml_model_proposal_agent

Public entry `ml_model_proposal_agent.py` and canonical `ml_model_proposal_agent.md`
define the node; `evidence_rendering.py` is private rendering support.
`ProposalInput`/`ProposalOutput` live in `src/agent/schemas/proposal.py`; the
incoming protocol is `ml_literature_review_to_ml_model_propose.py` and outgoing
protocol is `ml_model_propose_to_ml_model_impl.py`. Focused tests are under
`tests/unit/agent/ml_model_proposal_agent/`.
