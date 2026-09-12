# Time-estimation skill

The entry is run_skill(sandbox, **kwargs) in [wrapper.py](wrapper.py), with the
exact LLM-facing declaration in [skill_config.json](skill_config.json). It
estimates sequential training, inference and scoring wall time and returns a
policy decision/feasibility envelope. Inputs include model/train/loss configs,
training/evaluation sample sets, budget, optional data directory, and runtime
phase; the complete key contract is in
[evaluate_time_skill.md](evaluate_time_skill.md).

A real-dataset GPU warmup may build the model and execute bounded optimizer/
forward steps to measure cost; without CUDA/data it uses a static or
stored-observation estimate. It is not full candidate training or scoring.
The tuner calls it after VRAM preflight and before training; the
shared runtime decision policy owns admission semantics.

Focused seams are [tests/unit/agent/tune_ml_hyperparam_agent/test_evaluate_time_skill.py](../../../../tests/unit/agent/tune_ml_hyperparam_agent/test_evaluate_time_skill.py);
the batch sibling covers explicit inference-batch transport. Warmup/integration
execution is effectful.
