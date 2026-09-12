# tests/unit/ml_models

Model tests pin plugin loading, loss compatibility, descriptions, registry
population, and CPU forward output shapes on small synthetic tensors.

## Focused route

`.venv/bin/python -m pytest tests/unit/ml_models/test_arxiv_u3_bundled_isolation.py -q`

Owner: `src/ml_models/`; forward tests use CPU only and do not claim model quality.
The nested `fixtures/` file is a preserved cold-start description consumed by
model-loading tests; it is not a model recommendation or runtime default.
