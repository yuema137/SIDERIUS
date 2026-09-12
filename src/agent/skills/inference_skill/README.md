# Inference skill

run_skill(sandbox, **kwargs) in [wrapper.py](wrapper.py) forwards exp_id,
run_name, model_type, model/loss configs, optional evaluation sample set,
inference batch, runtime policy and task scopes to TidmadSandbox.execute_inference
in [sandbox_executor.py](../../../core/sandbox_executor.py). Its exact callable
declaration is [skill_config.json](skill_config.json); planning details are in
[inference_skill.md](inference_skill.md).

Production inference is an effectful isolated subprocess that loads a trained
checkpoint and writes denoised outputs. The wrapper does not validate configs
or score results; it preserves the run-bound sample scope. A stub sandbox can
exercise the same call boundary but is not scientific evidence.

Estimator and batch semantics are covered by [tests/unit/agent/inference_skill](../../../../tests/unit/agent/inference_skill/);
runtime checkpoint/inference coverage is under
[tests/unit/execute_tools](../../../../tests/unit/execute_tools/).
