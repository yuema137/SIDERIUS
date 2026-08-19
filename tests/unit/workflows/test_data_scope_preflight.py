"""
DS6b — run_workflow DataScope/HealthGate pre-flight.

Every failure here must fire BEFORE iteration 1's LLM calls: operator-config
contract violations raise ValueError, ingress-evidence mismatches raise
RunInvariantsViolation, and the pass path creates the workspace
run-invariants lock before the first agent is constructed (proven with a
sentinel on ResultInterpretationAgent — no LLM stubs required).
See docs/design/enable_partial_file_list.md (Commit DS6).
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from core.run_invariants import (
    RUN_INVARIANTS_BASENAME,
    RunInvariantsViolation,
    load_run_invariants,
)
from execute_tools.dataset_config import DataScope
from tests.helpers.metric_fixtures import shipped_spec
from workflows.model_exploration import run_workflow

PARTIAL = DataScope(file_indices=[4, 5, 6, 7, 8, 9])


def _seed_json(tmp_path, name="seed_full_scope", **overrides) -> str:
    """Minimal legacy (unstamped = full-scope) HyperparamTuningOutput JSON."""
    payload = {
        "run_name": name,
        "model_type": "punet",
        "file_index": 6,
        "status": "completed",
        "completed_rounds": 3,
        "total_attempts": 5,
        "best_exp_id": "exp_001",
        "best_denoising_score": 1.2,
        "started_at": "2026-04-27T10:00:00",
        "finished_at": "2026-04-27T11:00:00",
        **overrides,
    }
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(payload))
    return str(path)


def _run(tmp_path, **kwargs):
    defaults = dict(
        workspace=str(tmp_path / "ws"),
        run_name="preflight_test",
        source_paths=[],
        max_iterations=1,
        max_rounds=1,
    )
    defaults.update(kwargs)
    return run_workflow(**defaults)


class TestPreflightFailures:
    def test_partial_scope_without_gate_files(self, tmp_path):
        with pytest.raises(ValueError, match="health_gate_files"):
            _run(tmp_path, data_scope=PARTIAL)

    def test_partial_scope_with_non_snapshot_formal(self, tmp_path):
        with pytest.raises(ValueError, match="formal_strategy"):
            _run(
                tmp_path,
                data_scope=PARTIAL,
                health_gate_files=[4, 7, 9],
                formal_strategy="target",
            )

    def test_out_of_scope_gate_files(self, tmp_path):
        with pytest.raises(ValueError, match="DataScope"):
            _run(tmp_path, data_scope=PARTIAL, health_gate_files=[3, 7])

    def test_legacy_full_scope_seed_vs_partial_run(self, tmp_path):
        seed = _seed_json(tmp_path)
        with pytest.raises(RunInvariantsViolation, match="legacy = full scope"):
            _run(
                tmp_path,
                source_paths=[seed],
                data_scope=PARTIAL,
                health_gate_files=[4, 7, 9],
            )
        # Failed BEFORE the lock was stamped (invariant 3).
        assert load_run_invariants(str(tmp_path / "ws")) is None


class TestPreflightPass:
    def test_lock_created_before_first_agent(self, tmp_path):
        ws = str(tmp_path / "ws")
        with patch("workflows.model_exploration.ResultInterpretationAgent") as agent_cls:
            agent_cls.side_effect = RuntimeError("preflight-sentinel")
            with pytest.raises(RuntimeError, match="preflight-sentinel"):
                _run(
                    tmp_path,
                    data_scope=PARTIAL,
                    health_gate_files=[4, 7, 9],
                )
        # Pre-flight completed: lock written with the canonical values,
        # effective config materialized at the chain root.
        lock = load_run_invariants(ws)
        assert lock is not None
        assert lock.resolved_data_scope == [4, 5, 6, 7, 8, 9]
        assert lock.health_gate_enabled is True
        assert lock.health_config_sha256 is not None
        assert os.path.isfile(os.path.join(ws, "health_checks_effective.yaml"))
        assert os.path.isfile(os.path.join(ws, RUN_INVARIANTS_BASENAME))

    def test_stamped_matching_seed_passes_preflight(self, tmp_path):
        ws = str(tmp_path / "ws")
        with patch("workflows.model_exploration.ResultInterpretationAgent") as agent_cls:
            agent_cls.side_effect = RuntimeError("preflight-sentinel")
            with pytest.raises(RuntimeError, match="preflight-sentinel"):
                _run(tmp_path, data_scope=PARTIAL, health_gate_files=[4, 7, 9])
            lock = load_run_invariants(ws)
            seed = _seed_json(
                tmp_path,
                name="seed_partial_scope",
                resolved_data_scope=[4, 5, 6, 7, 8, 9],
                health_gate_enabled=True,
                health_config_sha256=lock.health_config_sha256,
                # Step 09a C2 — this seed is meant to REACH interpretation (the
                # sentinel below fires at agent construction). A seed that
                # reaches interpretation must carry the run's stamped
                # MetricSpec; the deliberately LEGACY seeds elsewhere in this
                # file fail earlier, on the invariants they are testing.
                metric_spec=shipped_spec().model_dump(mode="json"),
            )
            with pytest.raises(RuntimeError, match="preflight-sentinel"):
                _run(
                    tmp_path,
                    source_paths=[seed],
                    data_scope=PARTIAL,
                    health_gate_files=[4, 7, 9],
                )

    def test_second_run_with_different_config_fails_materialize_guard(self, tmp_path):
        """With gates enabled, changed operator inputs hit the materialized
        effective config's workspace-immutability guard first — an equally
        valid pre-LLM fail-fast (the lock guards what materialize can't:
        scope drift and enable flips)."""
        with patch("workflows.model_exploration.ResultInterpretationAgent") as agent_cls:
            agent_cls.side_effect = RuntimeError("preflight-sentinel")
            with pytest.raises(RuntimeError, match="preflight-sentinel"):
                _run(tmp_path, data_scope=PARTIAL, health_gate_files=[4, 7, 9])
        with pytest.raises(ValueError, match="mismatch"):
            _run(
                tmp_path,
                data_scope=DataScope(file_indices=[5, 6, 7, 8, 9]),
                health_gate_files=[5, 8],
            )

    def test_second_run_with_different_scope_fails_lock(self, tmp_path):
        """Gates disabled → no materialization, so scope drift is caught by
        the run-invariants lock itself."""
        with patch("workflows.model_exploration.ResultInterpretationAgent") as agent_cls:
            agent_cls.side_effect = RuntimeError("preflight-sentinel")
            with pytest.raises(RuntimeError, match="preflight-sentinel"):
                _run(tmp_path, data_scope=PARTIAL, health_gate_enabled=False)
        with pytest.raises(RunInvariantsViolation, match="resolved_data_scope"):
            _run(
                tmp_path,
                data_scope=DataScope(file_indices=[5, 6, 7, 8, 9]),
                health_gate_enabled=False,
            )


class TestDeprecatedStrategyParams:
    """DS7 — run_workflow's trial_strategy / target_files / eval_strategy
    params are accepted no-ops that warn when non-default."""

    def test_non_default_warns_before_any_work(self, tmp_path):
        with pytest.warns(DeprecationWarning, match="deprecated and IGNORED"):
            with pytest.raises(ValueError):
                # Combined with an invalid scope config so the run stops at
                # pre-flight right after warning — no stubs needed.
                _run(tmp_path, trial_strategy="target", data_scope=PARTIAL)
