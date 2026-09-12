# ML code validator node

`MLCodeValidatorAgent` checks a generated plugin before tuning: deterministic
load/config/description/test/forbidden-pattern checks, forward/backward probes,
and an advisory LLM review. It does not generate, train, or judge scientific
merit.

- [Entry and CLI](ml_code_validator_agent.py) · [full guide](ml_code_validator_agent.md)
- Input/output owners: [ValidatorInput/ValidatorOutput](../../agent/schemas/validator.py)
- Incoming [ml_model_impl_to_ml_model_valid](../../agent/schemas/protocols/ml_model_impl_to_ml_model_valid.py); outgoing [ml_model_valid_to_ml_model_tune](../../agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py)
- Focused real checks with controlled LLM seams: [tests/unit/agent/ml_code_validator_agent](../../../tests/unit/agent/ml_code_validator_agent/)

Private probe/prompt helpers are not public API; use the typed schemas and
protocols above.
