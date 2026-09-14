# ML code validator node

Use this node when a generated model plugin needs checking before tuning.
`MLCodeValidatorAgent` runs deterministic load/config/description/test checks,
forward/backward probes, and an advisory review. It does not generate, train,
or judge scientific merit.

- [Entry and CLI](ml_code_validator_agent.py) · [full guide](ml_code_validator_agent.md)
- Input/output owners: [ValidatorInput/ValidatorOutput](../../agent/schemas/validator.py)
- Incoming [ml_model_impl_to_ml_model_valid](../../agent/schemas/protocols/ml_model_impl_to_ml_model_valid.py); outgoing [ml_model_valid_to_ml_model_tune](../../agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py)
- Focused real checks with controlled LLM seams: [tests/unit/agent/ml_code_validator_agent](../../../tests/unit/agent/ml_code_validator_agent/)

Effects: validation reads generated plugin files and may call the configured
provider; it returns a typed verdict. For exact fields, refusals, and CLI
limitations, read the [node contract](ml_code_validator_agent.md). Private
probe/prompt helpers are implementation details.
