"""V18 wave-checkpoint summary script — unit tests over synthetic workspaces."""

from __future__ import annotations

import json

from scripts.v18_wave_summary import render, summarize_workspace


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
    assert any("no run_invariants_lock" in a for a in s["abnormal"])
    assert any("no iter_NNN" in a for a in s["abnormal"])
