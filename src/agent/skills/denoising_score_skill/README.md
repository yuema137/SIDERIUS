# Denoising-score skill

run_skill(sandbox, **kwargs) in [wrapper.py](wrapper.py) forwards exp_id,
run_name, model_type, model_config, train_config and loss_config to
TidmadSandbox.execute_scoring in [sandbox_executor.py](../../../core/sandbox_executor.py).
The callable declaration is [skill_config.json](skill_config.json).

The production path runs the scoring executor and writes/returns experiment
score artifacts; it is an effectful subprocess/data operation. Optional
run-bound task_scopes is forwarded rather than reacquired. This wrapper computes
no metric itself and does not validate the config.

The estimator route is [tests/unit/agent/denoising_score_skill/test_estimator.py](../../../../tests/unit/agent/denoising_score_skill/test_estimator.py);
executor/scoring integration belongs under
[tests/integration/execute_tools](../../../../tests/integration/execute_tools/).
Use a sandbox stub for pseudo-mode call-shape tests, not scientific evidence.

Detailed agent-facing contract: [denoising_score_skill.md](denoising_score_skill.md).
