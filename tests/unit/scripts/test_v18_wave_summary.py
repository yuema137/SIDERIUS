"""V18 wave-checkpoint summary script — unit tests over synthetic workspaces."""

from __future__ import annotations

import json

from scripts.v18_wave_summary import (
    expected_scope_from_name,
    main,
    read_exit_marker,
    render,
    summarize_workspace,
)


def _mk_iter(
    ws, n, status="completed", score=1.5, valid=1.2, model="arch_x", scope=None, records=None
):
    d = ws / f"iter_{n:03d}"
    (d / "sub").mkdir(parents=True)
    manifest = {
        "status": status,
        "model_name": model,
        "best_score": score,
        "best_valid_score": valid,
        "completed_rounds": 3,
        "resolved_data_scope": scope,
    }
    (d / "manifest.json").write_text(json.dumps(manifest))
    if records is not None:
        (d / "sub" / "summary_x.json").write_text(json.dumps(records))


def test_summary_aggregates_and_flags(tmp_path):
    ws = tmp_path / "v18_loss_04_09"
    ws.mkdir()
    (ws / "run_invariants_lock.json").write_text(
        json.dumps(
            {
                "resolved_data_scope": [4, 5, 6, 7, 8, 9],
                "health_gate_enabled": True,
                "health_config_sha256": "e" * 64,
            }
        )
    )
    _mk_iter(
        ws,
        1,
        score=1.5,
        valid=1.2,
        scope=[4, 5, 6, 7, 8, 9],
        records=[
            {"status": "success", "gate_action": "continue"},
            {"status": "failed_mode_collapse", "gate_action": "invalidate_round"},
            {"status": "error"},
        ],
    )
    _mk_iter(ws, 2, status="no_records", score=None, valid=None, model=None)
    _mk_iter(ws, 3, status="failed", score=None, valid=None, model=None)
    # Iter with a WRONG scope stamp → abnormal.
    _mk_iter(ws, 4, score=2.0, valid=1.9, model="arch_best", scope=[0, 1, 2])

    s = summarize_workspace(str(ws))
    assert s["resolved_data_scope"] == [4, 5, 6, 7, 8, 9]
    assert s["completed_iters"] == 2
    assert s["no_records_iters"] == 1
    assert s["failed_iters"] == 1
    assert s["best_raw_score"] == 2.0
    assert s["best_proposal"] == "arch_best"
    assert s["best_valid_score"] == 1.9
    assert s["success_records"] == 1
    assert s["collapse_records"] == 1
    assert s["error_records"] == 1
    assert s["gate_actions"] == {"continue": 1, "invalidate_round": 1}
    assert any("status=failed" in a for a in s["abnormal"])
    assert any("!= lock" in a for a in s["abnormal"])

    text = render([s])
    assert "v18_loss_04_09" in text
    assert "best raw score    : 2.0" in text
    assert "ABNORMAL" in text


def test_empty_workspace_reports_not_started(tmp_path):
    ws = tmp_path / "v18_arch_10_14"
    ws.mkdir()
    s = summarize_workspace(str(ws))
    assert any("run_invariants_lock" in a for a in s["abnormal"])
    assert any("no iter_NNN" in a for a in s["abnormal"])


# ---------------------------------------------------------------------------
# Audit rev — exit markers, scope-from-name, strict mode, hard checks
# ---------------------------------------------------------------------------

import yaml  # noqa: E402


def _mk_lock(ws, scope, sha="e" * 64, enabled=True):
    (ws / "run_invariants_lock.json").write_text(
        json.dumps(
            {
                "resolved_data_scope": scope,
                "health_gate_enabled": enabled,
                "health_config_sha256": sha,
            }
        )
    )


def _mk_effective(ws, scope):
    cfg = {
        "health_gates": [
            {
                "id": f"gate_{i}",
                "checks": [{"config": {"peek_file_indices": list(scope)}}],
            }
            for i in range(2)
        ]
    }
    (ws / "health_checks_effective.yaml").write_text(yaml.safe_dump(cfg))


class TestExitMarkers:
    def test_all_states(self, tmp_path):
        p = tmp_path / "x.exit"
        assert read_exit_marker(str(p)) == ("absent", None)
        p.write_text("EXIT=0")
        assert read_exit_marker(str(p)) == ("ok", 0)
        p.write_text("EXIT=3")
        assert read_exit_marker(str(p)) == ("failed", 3)
        p.write_text("garbage")
        assert read_exit_marker(str(p)) == ("malformed", None)

    def test_stale_marker_semantics(self, tmp_path):
        """A stale EXIT=0 marker with no workspace progress is still caught:
        the workspace-level checks (no lock / no iters) go ABNORMAL even
        though the marker itself reads ok."""
        ws = tmp_path / "v18_loss_04_09"
        ws.mkdir()
        (tmp_path / "v18_loss_04_09.exit").write_text("EXIT=0")
        s = summarize_workspace(str(ws), exit_dir=str(tmp_path))
        assert s["exit_state"] == "ok"
        assert any("no readable run_invariants_lock" in a for a in s["abnormal"])


class TestScopeFromName:
    def test_parses(self):
        assert expected_scope_from_name("v18_loss_04_09") == [4, 5, 6, 7, 8, 9]
        assert expected_scope_from_name("v18_arch_10_14") == [10, 11, 12, 13, 14]
        assert expected_scope_from_name("v18_loss_00_03") == [0, 1, 2, 3]
        assert expected_scope_from_name("random_name") is None


class TestHardChecks:
    def _healthy_ws(self, tmp_path, name="v18_loss_04_09", scope=None):
        scope = scope or [4, 5, 6, 7, 8, 9]
        ws = tmp_path / name
        ws.mkdir()
        _mk_lock(ws, scope)
        _mk_effective(ws, scope)
        _mk_iter(
            ws,
            1,
            scope=scope,
            records=[
                {
                    "status": "success",
                    "gate_action": "continue",
                    "health_gate_results": [
                        {
                            "gate_name": "g",
                            "aggregation": {
                                "files_requested": scope,
                                "files_completed": scope,
                            },
                        }
                    ],
                }
            ],
        )
        (tmp_path / f"{name}.exit").write_text("EXIT=0")
        return ws

    def test_healthy_strict_passes(self, tmp_path, capsys):
        ws = self._healthy_ws(tmp_path)
        code = main(["--strict", "--exit-dir", str(tmp_path), str(ws)])
        assert code == 0
        assert "abnormal          : none" in capsys.readouterr().out

    def test_name_scope_mismatch_flagged(self, tmp_path):
        ws = self._healthy_ws(tmp_path, name="v18_loss_04_09", scope=[0, 1, 2, 3])
        s = summarize_workspace(str(ws), exit_dir=str(tmp_path))
        assert any("scope encoded" in a for a in s["abnormal"])

    def test_effective_config_mismatch_flagged(self, tmp_path):
        ws = self._healthy_ws(tmp_path)
        _mk_effective(ws, [4, 7, 9])  # triplet instead of full scope
        s = summarize_workspace(str(ws), exit_dir=str(tmp_path))
        assert any("expected the full scope" in a for a in s["abnormal"])

    def test_out_of_scope_gate_attempt_flagged(self, tmp_path):
        ws = self._healthy_ws(tmp_path)
        _mk_iter(
            ws,
            2,
            scope=[4, 5, 6, 7, 8, 9],
            records=[
                {
                    "status": "success",
                    "health_gate_results": [
                        {
                            "gate_name": "g",
                            "aggregation": {"files_requested": [3, 10, 17]},
                        }
                    ],
                }
            ],
        )
        s = summarize_workspace(str(ws), exit_dir=str(tmp_path))
        assert any("attempted out-of-scope files [3, 10, 17]" in a for a in s["abnormal"])

    def test_out_of_scope_denoised_artifact_flagged(self, tmp_path):
        ws = self._healthy_ws(tmp_path)
        (ws / "iter_001" / "abra_validation_denoised_m_r_e_0015.h5").write_bytes(b"x")
        s = summarize_workspace(str(ws), exit_dir=str(tmp_path))
        assert any("OUT-OF-SCOPE denoised artifact" in a for a in s["abnormal"])

    def test_nonzero_exit_strict_fails(self, tmp_path):
        ws = self._healthy_ws(tmp_path)
        (tmp_path / "v18_loss_04_09.exit").write_text("EXIT=3")
        code = main(["--strict", "--exit-dir", str(tmp_path), str(ws)])
        assert code == 1

    def test_interim_mode_tolerates_running_chain(self, tmp_path):
        ws = self._healthy_ws(tmp_path)
        (tmp_path / "v18_loss_04_09.exit").unlink()
        code = main(["--exit-dir", str(tmp_path), str(ws)])
        assert code == 0  # non-strict: report but do not fail
