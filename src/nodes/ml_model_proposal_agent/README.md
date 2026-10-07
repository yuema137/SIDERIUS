# Model proposal node

Use this node when evidence must become a typed architecture proposal.
`MLModelProposalAgent` synthesizes interpretation, literature and task-bound
constraints into a validated architecture proposal. It owns prompt
orchestration and structural retries, not implementation, experiments, metric
semantics, or task declarations.

- [Entry and CLI](ml_model_proposal_agent.py) · [full guide](ml_model_proposal_agent.md)
- Schemas: [ProposalInput/ProposalOutput](../../agent/schemas/proposal.py)
- Incoming [ml_result_interp_to_ml_model_propose](../../agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py) and [ml_literature_review_to_ml_model_propose](../../agent/schemas/protocols/ml_literature_review_to_ml_model_propose.py); outgoing [ml_model_propose_to_ml_model_impl](../../agent/schemas/protocols/ml_model_propose_to_ml_model_impl.py)
- Prompt/schema coverage: [tests/unit/agent/ml_model_proposal_agent](../../../tests/unit/agent/ml_model_proposal_agent/)

Effects: the configured provider is called and structural retries may occur;
implementation and execution are later stages. Read the [node contract](ml_model_proposal_agent.md)
for exact input and refusal behavior. `evidence_rendering.py` is private.

In a workflow's LLM JSON file, `propose.comparison`, `propose.reasoning` and
`propose.proposing` select the model for each pipeline stage. Each selection
includes `provider`, `model_id`, `reasoning_effort` and `max_retries`. A correction
request uses the same selection as the stage being corrected. You can use one
model for all three stages or give each stage a different model.

Earlier releases silently used the reasoning selection for every stage. To
preserve that behavior for an existing experiment, copy its actual historical
reasoning selection into all three entries in the experiment's configuration.
Preserve retry and reasoning settings as well as the model name. The standalone
two-call legacy mode still uses the reasoning selection for both calls.
