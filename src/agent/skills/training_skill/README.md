# Training skill

run_skill(sandbox, **kwargs) in [wrapper.py](wrapper.py) forwards the resolved
experiment identity, model/train/loss configs, train and evaluation sample sets,
seeds, runtime policy, ordering and task scopes to TidmadSandbox.execute_training
in [sandbox_executor.py](../../../core/sandbox_executor.py). The exact legacy
tool declaration is [skill_config.json](skill_config.json); the fuller
input/output contract is [training_skill.md](training_skill.md).

Production launches [execute_tools/train_engine_sandbox.py](../../../execute_tools/train_engine_sandbox.py),
writes checkpoints/history and may consume real data/GPU. The wrapper validates
nothing and makes no ordering decision; the tuner and executor own those rules.
StubSandbox mirrors the boundary for pseudo-mode tests but performs no training
and is not scientific evidence.

Estimator tests are [tests/unit/agent/training_skill/test_estimator.py](../../../../tests/unit/agent/training_skill/test_estimator.py);
real training-loop coverage is [tests/integration/execute_tools/test_training_loop.py](../../../../tests/integration/execute_tools/test_training_loop.py).
