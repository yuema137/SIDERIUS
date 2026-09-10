"""Retained Step-11 ceiling and subprocess-boundary regressions.

The pre-change uncomposed argv oracle was retired with implicit task/data
selection. Explicit root transport is covered by test_step11_c4_data_root_transport.
Indexed naming is task-declared; test_step11_c6_deliverable_naming owns its
rendering contract.
"""

from __future__ import annotations

import inspect

import pytest

from core.execution_calibration import MalformedCeilingOverride
from core.sandbox_executor import _ROLE_DEFAULT_RSS_GB, _subprocess_rss_gb
from execute_tools.deliverable_spec import DeliverableNaming, bind_deliverable_naming


class TestRoleCeilingBaseline:
    """The retained role-ceiling compatibility contract."""

    def test_resolved_role_ceilings(self, monkeypatch):
        monkeypatch.delenv("SIDERIUS_SUBPROCESS_RSS_GB", raising=False)
        assert _subprocess_rss_gb("training") == 40
        assert _subprocess_rss_gb("inference") == 60
        assert _subprocess_rss_gb("scoring") == 24

    def test_declared_table_is_exactly_three_roles(self):
        assert _ROLE_DEFAULT_RSS_GB == {"training": 40, "inference": 60, "scoring": 24}

    def test_env_override_wins_for_every_role(self, monkeypatch):
        monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "7")
        for role in ("training", "inference", "scoring"):
            assert _subprocess_rss_gb(role) == 7

    def test_zero_disables_the_ceiling(self, monkeypatch):
        """`0` is the explicit pre-Fix-1 disable. R-11-5 preserves it."""
        monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "0")
        assert _subprocess_rss_gb("training") == 0

    def test_unknown_role_raises(self, monkeypatch):
        monkeypatch.delenv("SIDERIUS_SUBPROCESS_RSS_GB", raising=False)
        with pytest.raises(ValueError):
            _subprocess_rss_gb("compilation")


class TestMalformedOverrideRefusesLoudly:
    """R-11-5, landed by C3. **This class REPLACES its own C0 predecessor.**

    Per R-11-10 the pre-fix guard (`TestMalformedOverrideIsSilentToday`,
    which asserted the silent fallback) is not kept beside a post-fix twin
    — it is rewritten in place, so exactly one test states what a malformed
    override does.

    Note what is NOT asserted: nothing here claims a particular ceiling
    value follows a refusal. There is no resolved value after a refusal,
    and that is the point.
    """

    @pytest.mark.parametrize("bad", ["not-a-number", "12.5", "", "40G", " "])
    def test_unparseable_override_refuses(self, monkeypatch, bad):
        monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", bad)
        with pytest.raises(MalformedCeilingOverride):
            _subprocess_rss_gb("training")

    def test_negative_override_refuses(self, monkeypatch):
        monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "-1")
        with pytest.raises(MalformedCeilingOverride):
            _subprocess_rss_gb("training")

    def test_the_refusal_names_the_variable_and_the_bad_value(self, monkeypatch):
        """A refusal an operator cannot act on is barely better than a
        silent fallback.
        """
        monkeypatch.setenv("SIDERIUS_SUBPROCESS_RSS_GB", "4O")
        with pytest.raises(MalformedCeilingOverride) as exc:
            _subprocess_rss_gb("scoring")
        assert "SIDERIUS_SUBPROCESS_RSS_GB" in str(exc.value)
        assert "4O" in str(exc.value)


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
