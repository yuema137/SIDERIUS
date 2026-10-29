"""A parallel-v1 run locks its scheduling mode identically on both lock writers (B3-4b).

The worker's training admission and the native tuner each build the run lock;
`scheduling_mode` is canonical (decision B3-Q7), so a tuner that dropped the
budget would lock `serial` against the worker's `parallel-v1` and abort the run.
"""

from core.run_invariants import build_run_invariants
from core.runtime_control.scheduling import HostBudget


def test_worker_and_tuner_lock_the_same_parallel_mode(tmp_path):
    from agent.schemas.hyperparam_tuning import HyperparamTuningInput
    from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
        _lock_launch_identity,
    )
    from workflows.llm_config import TunerLLMConfig, WorkflowLLMConfig
    from workflows.run_config import WorkflowLaunchConfig
    from workflows.training_startup import workflow_lock_identity

    budget = HostBudget(
        gpus=(), host_memory_gib=8.0, cpu_slots=4, max_concurrent_units=2, source="host_reservation"
    )
    llm = WorkflowLLMConfig(tune=TunerLLMConfig(planner_strategy="native-timing-v1"))
    identities = {
        "worker": workflow_lock_identity(WorkflowLaunchConfig(), llm, None, budget),
        "tuner": _lock_launch_identity(
            HyperparamTuningInput(
                model_type="synthetic_model",
                planner_strategy="native-timing-v1",
                host_budget=budget,
            )
        ),
    }
    locked = {}
    for name, identity in identities.items():
        invariants, _ = build_run_invariants(
            resolved_data_scope=[0],
            health_gate_enabled=False,
            health_gate_files=None,
            health_checks_config=None,
            workspace=str(tmp_path / name),
            task_composition_fingerprint="a" * 64,
            include_runtime_identities=False,
            launch_identity=identity,
        )
        locked[name] = (invariants.scheduling_mode, invariants.host_budget)
    assert locked["worker"] == locked["tuner"]
    assert locked["worker"][0] == "parallel-v1"
    assert locked["worker"][1] is not None and locked["worker"][1].digest == budget.digest


def test_serial_tuner_input_keeps_its_bytes():
    from agent.schemas.hyperparam_tuning import HyperparamTuningInput

    payload = HyperparamTuningInput(model_type="synthetic_model").model_dump_json()
    assert "host_budget" not in payload
