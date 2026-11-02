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

A task can also declare a weighted evaluation formula. The scoring child evaluates
the source metrics, combines the referenced values into utility between 0 and 1,
and records each component's contribution. Higher utility wins candidate ranking;
Health checks still read the original scientific values. This requires the declared
evaluation capabilities to be available at launch. See the
[evaluation contract](../../../execute_tools/evaluation-contract.md#deterministic-selection-runtime)
for supported routes and explicit threshold units.
