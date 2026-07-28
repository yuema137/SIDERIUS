"""V19 PR 1 P1-C5 — CLI wrapper for the per-file best rebuild.

Verifies (a) the CLI writes the same canonical bytes as the shared
:func:`execute_tools.per_file_best.build_table` computation
(byte-equality between the incremental writer's path and the rebuild
CLI's path — design doc §3.7 A5), (b) ``--print-only`` never touches
disk, and (c) the CLI fails fast on missing workspaces.
"""

from __future__ import annotations

import hashlib
import json
import os
import runpy
import sys
from pathlib import Path

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from execute_tools.per_file_best import (
    TABLE_BASENAME,
    canonical_bytes,
    write_table,
)


def _record(exp_id: str, file_vector: list[float | None]) -> dict:
    return {
        "exp_id": exp_id,
        "status": "success",
        "model_type": "punet",
        "timestamp": "2026-07-27 00:00:00",
        "params": {},
        "logical_round": 1,
        "denoising_score": max(v for v in file_vector if v is not None),
        "file_vector": file_vector,
        "health_gate_results": [],
        "health_gate_enabled": False,
    }


def _write_committed_iter(workspace: str, iter_idx: int, records: list[dict]) -> str:
    run_name = f"iter_{iter_idx:03d}"
    iter_dir = os.path.join(workspace, run_name)
    model_dir = os.path.join(iter_dir, f"iteration_{iter_idx:03d}", "punet")
    os.makedirs(model_dir, exist_ok=True)
    out = HyperparamTuningOutput(
        run_name=run_name,
        model_type="punet",
        file_index=6,
        status="completed",
        completed_rounds=len(records),
        total_attempts=len(records),
        all_records=records,
        started_at="2026-07-27 00:00:00",
        finished_at="2026-07-27 00:00:01",
    )
    output_path = os.path.join(model_dir, f"run_output_{run_name}.json")
    with open(output_path, "w") as f:
        f.write(out.model_dump_json())
    with open(output_path, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    with open(os.path.join(model_dir, f"run_config_{run_name}.json"), "w") as f:
        json.dump({"formal_eval_portion": 1.0, "formal_strategy": "snapshot"}, f)
    with open(os.path.join(iter_dir, "manifest.json"), "w") as f:
        json.dump(
            {
                "status": "completed",
                "iteration_dir": iter_dir,
                "output_path": output_path,
                "model_name": "punet",
                "run_output_sha256": sha,
            },
            f,
        )
    return output_path


def _run_cli(monkeypatch, *argv: str) -> int:
    """Execute rebuild_per_file_best as a script (mirrors real CLI use);
    returns the exit code (0 = success). ``runpy`` propagates the
    script's ``SystemExit`` — catching it is expected."""
    script = Path(__file__).resolve().parents[3] / "scripts" / "rebuild_per_file_best.py"
    monkeypatch.setattr(sys, "argv", [str(script), *argv])
    try:
        runpy.run_path(str(script), run_name="__main__")
        return 0
    except SystemExit as e:
        code = e.code
        return int(code) if isinstance(code, int) else (0 if code is None else 1)


def test_cli_write_matches_incremental_bytes(tmp_path, monkeypatch, capsys):
    """A5 primary contract: bytes written by the CLI's --workspace path
    are IDENTICAL to bytes written by the incremental writer for the
    same committed inputs."""
    ws = str(tmp_path / "cli_write")
    os.makedirs(ws)
    _write_committed_iter(
        ws,
        1,
        [_record("a", file_vector=[0.5, 2.0, None] + [None] * 17)],
    )
    _write_committed_iter(
        ws,
        2,
        [_record("b", file_vector=[1.0, 1.5, None] + [None] * 17)],
    )

    # Incremental (chain-runner) writer → capture bytes.
    incremental_path = write_table(ws)
    incremental_bytes = Path(incremental_path).read_bytes()

    # Delete and let the CLI recreate.
    os.remove(incremental_path)
    assert _run_cli(monkeypatch, "--workspace", ws) == 0
    cli_bytes = Path(incremental_path).read_bytes()

    assert cli_bytes == incremental_bytes
    # Stdout mentions the written path.
    stdout = capsys.readouterr().out
    assert TABLE_BASENAME in stdout


def test_cli_print_only_writes_canonical_json_to_stdout(tmp_path, monkeypatch, capsysbinary):
    """--print-only must produce canonical bytes on stdout AND leave
    the workspace untouched (byte-for-byte equal to canonical_bytes on
    the same computation)."""
    ws = str(tmp_path / "print_only")
    os.makedirs(ws)
    _write_committed_iter(
        ws,
        1,
        [_record("a", file_vector=[3.0, None] + [None] * 18)],
    )

    table_path = Path(ws) / TABLE_BASENAME
    assert not table_path.exists()

    assert _run_cli(monkeypatch, "--workspace", ws, "--print-only") == 0
    printed = capsysbinary.readouterr().out
    assert not table_path.exists()

    # canonical_bytes over the SAME computation matches stdout exactly.
    from execute_tools.per_file_best import build_table

    assert printed == canonical_bytes(build_table(ws))


def test_cli_rejects_missing_workspace(tmp_path, monkeypatch):
    """Missing --workspace directory → exit 2 (fail fast, no writes)."""
    assert _run_cli(monkeypatch, "--workspace", str(tmp_path / "nonexistent")) == 2
