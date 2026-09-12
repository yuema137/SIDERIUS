# Model proposal node

`MLModelProposalAgent` synthesizes interpretation, literature and task-bound
constraints into a validated architecture proposal. It owns prompt
orchestration and structural retries, not implementation, experiments, metric
semantics, or task declarations.

- [Entry and CLI](ml_model_proposal_agent.py) · [full guide](ml_model_proposal_agent.md)
- Schemas: [ProposalInput/ProposalOutput](../../agent/schemas/proposal.py)
- Incoming [ml_result_interp_to_ml_model_propose](../../agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py) and [ml_literature_review_to_ml_model_propose](../../agent/schemas/protocols/ml_literature_review_to_ml_model_propose.py); outgoing [ml_model_propose_to_ml_model_impl](../../agent/schemas/protocols/ml_model_propose_to_ml_model_impl.py)
- Prompt/schema coverage: [tests/unit/agent/ml_model_proposal_agent](../../../tests/unit/agent/ml_model_proposal_agent/)

Tests control LLM seams; model implementation/execution is an effectful later
stage. `evidence_rendering.py` is private.
