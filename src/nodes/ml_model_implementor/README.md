# Model implementor node

`MLModelImplementor` converts a validated proposal into plugin code, config,
tests, description and loss provenance, validating generated sections before
returning paths. It does not choose the architecture or certify/train it.

- [Entry and CLI](ml_model_implementor.py) · [full guide](ml_model_implementor.md)
- Schemas: [ImplementorInput/ImplementorOutput](../../agent/schemas/implementor.py)
- Incoming [ml_model_propose_to_ml_model_impl](../../agent/schemas/protocols/ml_model_propose_to_ml_model_impl.py); outgoing [ml_model_impl_to_ml_model_valid](../../agent/schemas/protocols/ml_model_impl_to_ml_model_valid.py)
- Prompt/code/schema coverage: [tests/unit/agent/ml_model_implementor](../../../tests/unit/agent/ml_model_implementor/)

Generation uses controlled LLM seams in tests; generated plugin execution and
training are effectful downstream checks. Rendering helpers are private.
