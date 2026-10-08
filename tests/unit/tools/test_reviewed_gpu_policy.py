"""The selected GPU policy must survive review and the actual standard handoff."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.unit.tools.test_reviewed_standard_launch import reviewed
from tests.unit.tools.test_setup_environment import setup as setup
from tools.setup_review.semantic_packet import build_packet


def selected_policy():
    return {
        "phase_measurement_budget_seconds": 47.0,
        "worker_rss_limit_bytes": 1073741824,
        "startup_ack_timeout_seconds": 3.0,
        "startup_receipt_limit_bytes": 65536,
        "protection": {
            "max_sample_age_seconds": 2.0,
            "observation": {
                "fast_interval_ms": 100,
                "fast_window_ms": 2000,
                "steady_interval_ms": 500,
                "join_timeout_ms": 1000,
            },
            "control": {"poll_seconds": 0.05, "grace_seconds": 0.1, "reap_seconds": 1.0},
        },
    }


@pytest.mark.parametrize("change_policy", [False, True])
def test_selected_policy_reaches_checked_launch_or_refuses_changed_file(tmp_path, change_policy):
    # A cold process isolates Quickstart's plugin identity, while the helper runs
    # real composition/lock/launch owners and stops before workflow execution.
    script = """
import json, sys
from pathlib import Path
import pytest
from tests.unit.tools.test_reviewed_standard_launch import _exercise_real_standard_main
with pytest.MonkeyPatch.context() as patch:
    _exercise_real_standard_main(
        Path(sys.argv[1]), patch, False,
        gpu_policy=json.loads(sys.argv[2]), change_policy=sys.argv[3] == 'True',
    )
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(tmp_path),
            json.dumps(selected_policy()),
            str(change_policy),
        ],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_policy_packet_uses_saved_allowlisted_fields_without_defaults_or_resolution(
    setup, tmp_path, monkeypatch
):
    report, _, _, _ = reviewed(setup, tmp_path, monkeypatch)
    before = build_packet(report)
    assert "declared_gpu_execution_policy" not in before
    policy = selected_policy()
    del policy["startup_ack_timeout_seconds"]
    expected = json.loads(json.dumps(policy))
    policy["private_extra"] = "must-not-transmit"
    policy["protection"]["private_extra"] = "must-not-transmit"
    policy["protection"]["control"]["private_extra"] = "must-not-transmit"
    policy["protection"]["observation"]["private_extra"] = "must-not-transmit"
    snapshot = report.model_copy(
        update={"launch_settings": {**report.launch_settings, "gpu_execution_policy": policy}}
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("semantic projection must not resolve policy or hardware")

    monkeypatch.setattr(
        "core.runtime_control.gpu_execution_policy.load_gpu_execution_policy", forbidden
    )
    monkeypatch.setattr("core.hardware_context.inspect_gpu_runtime", forbidden)
    packet = build_packet(snapshot)
    assert packet.pop("declared_gpu_execution_policy") == expected
    assert packet == before
    assert "must-not-transmit" not in json.dumps(packet)
