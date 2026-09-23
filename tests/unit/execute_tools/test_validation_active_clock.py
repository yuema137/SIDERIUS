"""A short validation scope must survive long intervening training epochs.

Deleting these tests loses production-pass/session coverage of phase clock
attribution: the original code rejects pass two despite subsecond validation.
"""

import json
from types import SimpleNamespace

import pytest
import torch
from torch.utils.data import Dataset

import core.runtime_control.adaptive as adaptive
import execute_tools.train_engine_sandbox as engine
from core.runtime_control.session import RuntimeControlPolicy, RuntimeVerificationSession
from core.runtime_control.workload import ResolvedPhaseWorkload
from ml_models.models_format_sandbox import LossConfig


@pytest.mark.parametrize("setup_stall", [0.0, 61.0])
def test_validation_intervals_exclude_training_but_include_setup(
    monkeypatch, tmp_path, setup_stall
):
    clock = [100.0]
    monkeypatch.setattr(adaptive, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(engine, "time", SimpleNamespace(perf_counter=lambda: clock[0]))

    class Rows(Dataset):
        def __len__(self):
            return 480

        def __getitem__(self, index):
            clock[0] += 0.00075
            value = torch.tensor([float(index), 1.0])
            return value, value

    def dataset(*_):
        clock[0] += setup_stall
        return Rows()

    path = tmp_path / "runtime.json"
    session = RuntimeVerificationSession(
        str(path), RuntimeControlPolicy(operator_budget_seconds=7200)
    )
    session.complete_setup(storage_provenance={})
    session.record_phase_workload(
        "validation",
        ResolvedPhaseWorkload(
            phase="validation",
            unit="validation_sample",
            unit_count=960,
        ),
    )
    verifier = session.start_phase_verification("validation", unit="validation_sample")
    decisions = []

    def persist():
        session.complete_phase_verification(
            "validation", verifier, source="real_validation_verification"
        )
        decisions.append(session.decide_admission(stage="post_validation_verification").decision)

    model = torch.nn.Identity().train()
    for epoch in range(2):
        if epoch:
            clock[0] += 300  # Other production work, not validation calibration.
        result, count, _ = engine.observe_validation(
            model=model,
            criterion=torch.nn.MSELoss(),
            model_cfg=SimpleNamespace(model_type="wavenet"),
            loss_cfg=LossConfig(loss_type="smooth_l1"),
            model_io=None,
            device=torch.device("cpu"),
            data_path=SimpleNamespace(validation_dataset=dataset),
            task_eval_scope=object(),
            data_dir="unused",
            batch_size=8,
            verifier=verifier,
            on_verified=persist,
        )
        assert result == 0 and count == 480 and model.training
        if setup_stall:
            assert decisions == ["rejected"]
            assert "wall-time cap exhausted" in verifier.failure_reason
            break
        if epoch == 0:
            assert not verifier.is_terminal  # First 60 batches lack 500ms of evidence.

    record = json.loads(path.read_text())["components"]["validation"]
    if not setup_stall:
        assert decisions == ["admitted"]
        assert record["prediction"]["formal_execution_eligible"] is True
        assert record["prediction"]["predicted_seconds"] == pytest.approx(0.72)
        detail = record["measurement"]["detail"]
        assert detail["verification_excluded_inactive_seconds"] == pytest.approx(300)
        assert detail["verification_active_wall_ms"] < 1000
