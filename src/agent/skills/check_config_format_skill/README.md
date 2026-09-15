# Configuration-format skill

The wrapper entry is run_skill(sandbox, **kwargs) in [wrapper.py](wrapper.py).
It reads no kwargs: it returns JSON Schema snapshots for the registered model,
loss and training Pydantic configs plus architecture quick notes. The exact
tool declaration is [skill_config.json](skill_config.json).

This is a pure in-process format consultation; it does not spawn a subprocess,
touch data, use the network, or validate a candidate's runtime behaviour.
Config authority remains the imported ml_models.models_format_sandbox models,
not this README or the quick notes.

Detailed agent-facing contract: [check_config_format_skill.md](check_config_format_skill.md).

Focused contract coverage is [tests/unit/agent/test_skill_spec.py](../../../../tests/unit/agent/test_skill_spec.py);
schema behaviour is covered by model/schema tests. Callers should consume
returned data.schemas and validate through the owning Pydantic classes.
