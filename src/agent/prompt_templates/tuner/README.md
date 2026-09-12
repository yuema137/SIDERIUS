# `tuner/`

Owns deterministic substitutions for the tuner's LLM-facing prompt content
in [`rendering.py`](rendering.py). Tokens are read from landed authorities
(`MODEL_REGISTRY`, run-bound dataset/model contracts, loss defaults, effective
health configuration, and tuner policy); prose that has no authority remains
literal in the caller's templates. This child has no task-block loader and
`README.md` is never selected as model input.

The renderer is imported by the tuner prompt path, not a workflow entrypoint.
Use the tuner prompt goldens in
[`tests/unit/agent/tune_ml_hyperparam_agent`](../../../../tests/unit/agent/tune_ml_hyperparam_agent/)
when changing a token or its authority.
