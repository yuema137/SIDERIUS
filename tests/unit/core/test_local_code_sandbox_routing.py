"""Actual sandbox converters, with CPU-only/in-process child boundary substitution."""

from __future__ import annotations

import subprocess

import pytest

from core.local_code import LocalCodeError, bind_code_package
from core.local_code.child import main as child_main
from tests.unit.core.test_local_code_failure import package_and_env
from tests.unit.core.test_sandbox_executor import (
    EXP_ID,
    LOSS_CFG,
    MODEL_CFG,
    RUN_NAME,
    TRAIN_CFG,
    sandbox,
)


@pytest.mark.parametrize("integrity", [True, False])
def test_training_outer_catch_preserves_only_named_refusal(sandbox, monkeypatch, integrity):
    failure = (
        LocalCodeError("immutable source refused") if integrity else RuntimeError("candidate error")
    )

    def process(*args, **kwargs):
        raise failure

    monkeypatch.setattr("core.sandbox_executor._run_observed_subprocess", process)
    if integrity:
        with pytest.raises(LocalCodeError) as raised:
            sandbox.execute_training(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        assert raised.value is failure
    else:
        result = sandbox.execute_training(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
        assert result["status"] == "error"
        assert "candidate error" in result["message"]


@pytest.mark.parametrize("unwind", [True, False])
def test_scoring_checks_guard_produced_report_before_reading_or_merging_results(
    sandbox, tmp_path, monkeypatch, unwind
):
    package = package_and_env(tmp_path, monkeypatch)
    target = tmp_path / "refuse.py"
    target.write_text(
        "from core.local_code import LocalCodeError\nraise LocalCodeError('late helper refusal')\n"
    )
    reads = []

    def process(argv, *, env, **kwargs):
        # The production guard publishes its own typed report. Model a child
        # that consumed the failure status but left the shared report intact.
        with monkeypatch.context() as child_env:
            for key, value in env.items():
                child_env.setenv(key, value)
            assert child_main(["script", str(target)]) == 78
        if unwind:
            raise OSError("parent-side child completion failed")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr("core.sandbox_executor.subprocess.run", process)
    monkeypatch.setattr("core.sandbox_executor.json.load", lambda *a, **kw: reads.append(a))
    with bind_code_package(package), pytest.raises(LocalCodeError, match="late helper refusal"):
        sandbox.execute_scoring(EXP_ID, RUN_NAME, "fcnet", MODEL_CFG, TRAIN_CFG, LOSS_CFG)
    assert reads == []
    # Existing prelaunch behavior creates an empty score file. It remains
    # empty; no scoring read/merge or scientific result publication occurred.
    assert (tmp_path / f"records/{RUN_NAME}/score_results_fcnet_{EXP_ID}.json").read_text() == "{}"
    assert not list(tmp_path.rglob("experiment_results_*.json"))
