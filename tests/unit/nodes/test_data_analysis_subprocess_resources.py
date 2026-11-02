"""Successful fixture pipelines retain real evidence after cold-start delays."""

from pathlib import Path
from typing import Literal

import pytest

from .test_data_analysis_agent import (
    test_generated_program_is_persisted_before_plan_and_certified_as_evidence as assert_generated,
)
from .test_data_analysis_agent import (
    test_standalone_agent_runs_typed_pipeline_and_persists_bounded_report as assert_reference,
)


@pytest.mark.allow_real_subprocess
@pytest.mark.parametrize("pipeline", ["reference", "generated"])
def test_pipeline_preserves_evidence_after_slow_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pipeline: Literal["reference", "generated"]
) -> None:
    """Reverting fixture allocations must expire before the evidence assertions."""
    from agent.data_analysis import executor

    popen = executor.subprocess.Popen
    launches: list[str] = []

    def delayed_start(cmd: list[str], *args, **kwargs):
        if pipeline == "reference" and cmd[1:3] == ["-m", "agent.data_analysis.worker_main"]:
            launches.append("reference")
            cmd = [
                cmd[0],
                "-c",
                "import time, runpy, sys; time.sleep(6); "
                "sys.argv[0] = 'agent.data_analysis.worker_main'; "
                "runpy.run_module('agent.data_analysis.worker_main', run_name='__main__')",
                *cmd[3:],
            ]
        elif pipeline == "generated" and "/runner/runner.py" in cmd and "--source" in cmd:
            launches.append("generated")
            runner_index = cmd.index("--") + 2
            assert cmd[runner_index] == "/runner/runner.py"
            cmd = [
                *cmd[:runner_index],
                "-c",
                "import time, runpy, sys; time.sleep(6); "
                "sys.argv[0] = '/runner/runner.py'; "
                "runpy.run_path('/runner/runner.py', run_name='__main__')",
                *cmd[runner_index + 1 :],
            ]
        return popen(cmd, *args, **kwargs)

    monkeypatch.setattr(executor.subprocess, "Popen", delayed_start)
    if pipeline == "reference":
        assert_reference(tmp_path)
        assert launches == ["reference"] * 3  # interface, parameters, execution
    else:
        assert_generated(tmp_path)
        assert launches == ["generated"]
