"""C9c — an infrastructure ABORT terminates the CHAIN, not just the attempt.

The two consequences that matter:

    candidate rejection      -> attempt stops, chain may continue
    infrastructure rejection -> attempt stops AND the chain halts

Chain termination reuses the mechanism the repository already has for
non-continuable states: the `.chain_halted` sentinel plus exit code 3.
The sentinel is what stops a QUEUED next iteration — SDSC's `afterany`
dependency starts the next job whatever the previous exit code was — and
exit 3 is what stops the foreground loop. The `reason` field keeps the
two producers of that sentinel distinguishable.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_runner():
    """Load run_one_iteration.py from THIS checkout (portability rule)."""
    path = REPO_ROOT / "sdsc_submission_scripts" / "run_one_iteration.py"
    spec = importlib.util.spec_from_file_location("_c9c_runner", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["_c9c_runner"] = module
    spec.loader.exec_module(module)
    return module


runner = _load_runner()


class _Output:
    """Minimal stand-in for HyperparamTuningOutput's read fields."""

    def __init__(self, termination_reason: str, status: str = "failed"):
        self.termination_reason = termination_reason
        self.status = status


class TestTerminationStatePrecedence:
    def _compute(self, **over):
        from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
            _compute_termination_state,
        )

        kwargs = dict(
            completed_rounds=0,
            max_rounds=5,
            consecutive_fails=0,
            max_fail_rounds=3,
        )
        kwargs.update(over)
        return _compute_termination_state(**kwargs)

    def test_infrastructure_abort_is_reported(self):
        assert self._compute(evidence_channel_failure="registry corrupt") == (
            "failed",
            "infrastructure_abort",
        )

    def test_it_outranks_every_other_terminal_reason(self):
        """If the evidence channel is broken, the other classifications
        this run made are themselves untrustworthy."""
        assert self._compute(
            evidence_channel_failure="telemetry gone",
            scope_violation_reason="scope violated",
            completed_rounds=5,
            consecutive_fails=3,
        ) == ("failed", "infrastructure_abort")

    def test_without_it_the_existing_precedence_is_untouched(self):
        # (the gate_aborted input was retired with SKIP_ITER — F-SCANC-1;
        # "aborted_by_gate" survives only as a historical record value)
        assert self._compute(scope_violation_reason="x") == ("failed", "scope_violation")
        assert self._compute(completed_rounds=5) == ("completed", "completed")
        assert self._compute(consecutive_fails=3) == ("partial", "aborted_fail_rounds")
        assert self._compute() == ("partial", "completed")

    def test_the_schema_accepts_the_new_reason(self):
        from agent.schemas.hyperparam_tuning import HyperparamTuningOutput

        field = HyperparamTuningOutput.model_fields["termination_reason"]
        assert "infrastructure_abort" in str(field.annotation)


class TestAbortDetection:
    def test_detects_the_typed_signal(self):
        assert runner._infrastructure_abort_reason([_Output("infrastructure_abort")])

    @pytest.mark.parametrize(
        "reason",
        ["completed", "aborted_fail_rounds", "aborted_by_gate", "scope_violation"],
    )
    def test_other_terminal_reasons_do_not_halt_the_chain(self, reason):
        """A candidate-level or gate-level end is NOT an infrastructure
        abort — the chain continues under the existing policy."""
        assert runner._infrastructure_abort_reason([_Output(reason)]) is None

    def test_no_results_is_not_an_abort(self):
        assert runner._infrastructure_abort_reason([]) is None
        assert runner._infrastructure_abort_reason(None) is None


class TestHaltMarker:
    def test_the_sentinel_records_a_distinguishable_reason(self, tmp_path):
        path = runner._write_halt_marker(
            str(tmp_path), {"reason": "infrastructure_abort", "detail": "registry corrupt"}
        )
        payload = json.loads(Path(path).read_text())
        assert payload["reason"] == "infrastructure_abort"
        assert payload["detail"] == "registry corrupt"

    def test_the_sentinel_stops_the_next_iteration(self, tmp_path):
        assert runner._check_halt_marker(str(tmp_path)) is False
        runner._write_halt_marker(str(tmp_path), {"reason": "infrastructure_abort"})
        assert runner._check_halt_marker(str(tmp_path)) is True

    def test_the_consecutive_failure_brake_is_a_different_reason(self):
        """The two producers of the sentinel must stay distinguishable, so
        an infrastructure abort is never read as a fail-round streak."""
        source = (REPO_ROOT / "sdsc_submission_scripts" / "run_one_iteration.py").read_text(
            encoding="utf-8"
        )
        assert '"reason": "consecutive_failure_brake"' in source
        assert '"reason": "infrastructure_abort"' in source


class TestExitContract:
    """The halt path must exit 3 (halt), not 0 (continue) or 1 (ordinary
    failure) — and it must run AFTER the manifest is written so the
    operator keeps the diagnostics."""

    def test_the_abort_branch_exits_three_after_writing_the_manifest(self):
        source = (REPO_ROOT / "sdsc_submission_scripts" / "run_one_iteration.py").read_text(
            encoding="utf-8"
        )
        manifest_at = source.index("    manifest = write_manifest(")
        abort_at = source.index("_abort_reason = _infrastructure_abort_reason(results)")
        assert manifest_at < abort_at, "artifacts must be preserved before halting"
        tail = source[abort_at : abort_at + 1600]
        assert "sys.exit(3)" in tail
        assert "_write_halt_marker(" in tail

    def test_gate_exhaustion_still_exits_zero(self):
        """no_records means "no candidate passed", not "infrastructure is
        broken" — that chain continues, and must keep doing so."""
        source = (REPO_ROOT / "sdsc_submission_scripts" / "run_one_iteration.py").read_text(
            encoding="utf-8"
        )
        block = source[source.index('if manifest["status"] == "no_records":') :]
        assert "sys.exit(0)" in block[:1200]
