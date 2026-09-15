# `check_config_format_skill` agent contract

## Boundary

This skill is a read-only, in-process schema consultation. It wraps
`ml_models.models_format_sandbox`; the imported Pydantic classes are authority
for accepted values. This document and returned quick notes are not schema or
semantic authority.

## Invocation and output

```python
run_skill(sandbox, **kwargs) -> dict[str, Any]
```

`sandbox` and all keyword arguments are accepted but ignored. The declaration
in `skill_config.json` consequently has an empty parameter object. A normal
return is an envelope with `status="success"`, a message, and `data` containing
JSON schemas named `PUNetConfig`, `AEConfig`, `TransformerConfig`, `LossConfig`,
and `TrainConfig`, plus a `quick_notes` string. Schemas are generated at call
time with each model's `model_json_schema()`.

If schema construction raises, the wrapper returns `status="error"` and a
message; it does not re-raise that exception.

## Effects and authority

The wrapper does not spawn processes, access data, write files, or use the
network. It does not validate candidate configurations or enforce semantic
compatibility in `quick_notes`; callers must use resolved task contracts and
execution validators before execution. The schemas are generated from the
current imported Pydantic models at call time, and the live wrapper and models
determine the actual response until deliberately changed.

`quick_notes` is intentionally one generic reminder: schemas describe format;
resolved task contracts and execution validators own model/loss compatibility,
output shape, class cardinality, segmentation legality, and resource limits.

## Callers and evidence

Agent tooling consults this skill before proposing or validating formats.
`tests/unit/agent/test_skill_spec.py` covers the generic declaration shape;
model/schema tests cover the Pydantic authority. These are contract tests, not
scientific training evidence.
