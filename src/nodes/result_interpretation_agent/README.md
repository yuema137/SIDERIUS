# Result interpretation node

Use this node to turn validated tuning records into evidence for the next
proposal. `ResultInterpretationAgent` turns validated tuning records into bounded
cross-model evidence, diagnoses and prediction outcomes, carrying typed
knowledge/vocabulary state to the next proposal iteration. It does not rescore
data, define metric direction, or invent task guidance.

- [Entry and CLI](result_interpretation_agent.py) · [full guide](result_interpretation_agent.md)
- Schemas: [InterpretationInput/InterpretationOutput](../../agent/schemas/interpretation.py)
- Incoming [ml_model_tune_to_ml_result_interp](../../agent/schemas/protocols/ml_model_tune_to_ml_result_interp.py); outgoing [ml_result_interp_to_ml_model_propose](../../agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py)
- Deterministic evidence/ordering and controlled LLM coverage: [tests/unit/agent/result_interpretation_agent](../../../tests/unit/agent/result_interpretation_agent/)

Effects: a provider call may be made and the resulting typed record is passed
to the workflow. Read the [node contract](result_interpretation_agent.md) for
exact bounds and refusal behavior. `evidence.py`, `ordering.py`, and
`prediction.py` are private helpers.
