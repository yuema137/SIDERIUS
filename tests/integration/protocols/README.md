# tests/integration/protocols

Protocol tests exercise typed hand-offs between agent schemas. Inputs are
synthetic; the tests catch dropped fields and invalid boundary wiring without
LLM or training. The tune-to-interpret conversion is owned directly by its
focused unit family rather than a duplicate task-specific live workflow.

## Source and route

`.venv/bin/python -m pytest tests/integration/protocols/test_implement_to_validate.py -q`

```bash
.venv/bin/python -m pytest \
  tests/unit/agent/protocols/test_ml_model_tune_to_ml_result_interp.py -q
```

Owner: `src/agent/schemas/protocols/`. See the [integration map](../README.md).
