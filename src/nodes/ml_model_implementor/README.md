# src/nodes/ml_model_implementor

Public entry `ml_model_implementor.py` and canonical `ml_model_implementor.md`
define the node. `ImplementorInput`/`ImplementorOutput` live in
`src/agent/schemas/implementor.py`; the outgoing adapter is
`ml_model_impl_to_ml_model_valid.py`. Focused tests: `tests/unit/agent/ml_model_implementor/`.
