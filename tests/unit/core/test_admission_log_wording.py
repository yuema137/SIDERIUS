"""Missing phase requirements must be explained without internal design references."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.runtime_control.admission import GpuAdmissionPolicy
from core.runtime_control.gpu_accounting import DeviceIdentity, GpuAccountingSnapshot
from core.sandbox_executor import _admission_refusal


@pytest.mark.parametrize("phase", ["training", "inference"])
@pytest.mark.parametrize("enforcement", ["observe_only", "enforce"])
def test_missing_requirement_log_explains_actual_enforcement(
    phase: str, enforcement: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Reverting the reason restores PR/design jargon in the real worker log."""
    device = DeviceIdentity(uuid="GPU-aaaa-0000", physical_index=0)
    snapshot = GpuAccountingSnapshot(
        device=device,
        telemetry_available=True,
        device_total_mib=32_000,
        device_used_mib=1_000,
        own_tree_mib=0,
        other_mib=1_000,
        other_process_count=1,
        per_pid_total_mib=1_000,
        unattributed_mib=0,
        accounting_skew_mib=0,
    )
    sandbox = SimpleNamespace(
        device_identity=device,
        run_name="log-wording",
        admission_policy=GpuAdmissionPolicy.model_validate(
            {"mode": "formal", "enforcement": enforcement}
        ),
    )
    with patch("core.runtime_control.gpu_accounting.sample", return_value=snapshot):
        result = _admission_refusal(sandbox, phase=phase)

    log = capsys.readouterr().out
    assert "PR " not in log
    assert "D-B" not in log
    assert "no applicable measured GPU memory requirement is available for this phase" in log
    assert "a predicted estimate cannot establish the required memory" in log
    if enforcement == "observe_only":
        assert result is None
        assert f"{phase} WOULD BE REFUSED (observe_only, policy_unavailable)" in log
        assert "Proceeding because enforcement_observe_only" in log
    else:
        assert result is not None
        assert result["admission"]["reason_code"] == "policy_unavailable"
        assert f"{phase} refused:" in log
        assert "Proceeding" not in log
