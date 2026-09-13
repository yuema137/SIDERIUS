"""Named skill errors unwind the real tuner; ordinary candidate errors still retry."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.local_code import LocalCodeError
from tests.helpers.recording_sandbox import RecordingSandbox
from tests.helpers.step00_pseudo_iteration import run_bounded_pseudo_iteration

pytestmark = pytest.mark.usefixtures("synthetic_run_authorities")


@pytest.mark.parametrize("integrity", [True, False])
def test_real_tuner_skill_failure_stops_only_for_package_integrity(
    tmp_path, monkeypatch, integrity
):
    calls = []
    failure = (
        LocalCodeError("undeclared task helper") if integrity else RuntimeError("candidate error")
    )

    def training(self, *args, **kwargs):
        calls.append(kwargs["exp_id"])
        raise failure

    monkeypatch.setattr(RecordingSandbox, "execute_training", training)
    preflight = json.loads(
        (Path(__file__).parent / "fixtures/step00_preflight_results.json").read_text()
    )["results"]
    # Admission is an existing recorded boundary; no device/process work occurs.
    if integrity:
        with pytest.raises(LocalCodeError) as raised:
            run_bounded_pseudo_iteration(tmp_path, monkeypatch, preflight_results=preflight)
        assert raised.value is failure
        assert len(calls) == 1
    else:
        output, _, sandbox, _ = run_bounded_pseudo_iteration(
            tmp_path, monkeypatch, preflight_results=preflight
        )
        assert len(calls) >= 2
        assert output.best_denoising_score is None
        assert not any(record.get("status") == "success" for record in sandbox.get_summary())
