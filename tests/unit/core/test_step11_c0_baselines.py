"""Retained Step-11 ceiling and subprocess-boundary regressions.

The pre-change uncomposed argv oracle was retired with implicit task/data
selection. Explicit root transport is covered by test_step11_c4_data_root_transport.
Indexed naming is task-declared; test_step11_c6_deliverable_naming owns its
rendering contract.
"""

from __future__ import annotations

import inspect

from execute_tools.deliverable_spec import DeliverableNaming, bind_deliverable_naming


def test_sandbox_uses_declared_cleanup_authority(
    tmp_path, synthetic_run_authorities, synthetic_physical_data_root
):
    """A task's template, not a historical filename, must reach the executor."""
    from core.sandbox_executor import TidmadSandbox

    declared = DeliverableNaming(prefix="fixture_prediction", extension=".npz", index_width=3)
    with bind_deliverable_naming(declared):
        sandbox = TidmadSandbox(run_name="cleanup", workspace=str(tmp_path))
    assert sandbox.deliverable_naming is declared
    assert (
        sandbox.deliverable_naming.attempt_glob(
            model_type="model", run_name="cleanup", exp_id="attempt"
        )
        == "fixture_prediction_model_cleanup_attempt_*.npz"
    )


def test_scoring_launch_semantics_unchanged():
    """Scoring remains direct; GPU children alone use the observed seam."""
    from core import sandbox_executor

    src = inspect.getsource(sandbox_executor.TidmadSandbox.execute_scoring)
    assert "subprocess.run(" in src
    assert "_run_observed_subprocess" not in src
