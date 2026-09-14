# `tuner/`

Owns deterministic substitutions for the tuner's LLM-facing prompt content
in [`rendering.py`](rendering.py). Tokens are read from landed authorities
(`MODEL_REGISTRY`, run-bound dataset/model contracts, loss defaults, effective
health configuration, and tuner policy); prose that has no authority remains
literal in the caller's templates. This child has no task-block loader and
`README.md` is never selected as model input.

The renderer is imported by the tuner prompt path, not a workflow entrypoint.
Description loading is governed by the typed `DescriptionSourcePolicy`: legacy
callers may use bundled manuals, while composed callers resolve only inline,
carried, workspace/generated, and declared task-pack sources. Missing composed
description prose is an ordinary absence and does not trigger a bundled
fallback.
For composed runs, `loss_context.py` carries declared ModelIO semantic/temporal
facts and the optional validated task objective on `TunerTaskRender`.
`loss_rendering.py` uses the existing execution compatibility authority's
builtin offers for both planner messages, examples and loss-only guidance.
Missing composed ModelIO or contradictory fixed-model declarations refuse before
the planner call. A task objective is shown exactly and is not a tuning lever;
the deterministic downstream override remains authoritative.

This is builtin filtering, not custom-loss compatibility certification. Custom
registration/selection and locked custom objectives retain their existing path;
prediction/target compatibility declarations for custom code remain separate work.
Legacy rendering (no loss context) preserves the original prompt bytes.

Use the tuner prompt goldens in
[`tests/unit/agent/tune_ml_hyperparam_agent`](../../../../tests/unit/agent/tune_ml_hyperparam_agent/)
when changing a token or its authority.
