"""Unit tests for ``scripts/inspect_run_state.py``.

Covers the chain-layout walk introduced in Phase 6.8 Task 2 Commit 12,
the ``--next-iter`` machine-readable output used by ``run_chain.sh
--auto_resume``, the legacy-layout guard reused from
``core.resume.validate_workspace_layout``, and a regression smoke for
the original ``--layout run`` mode.

The fixture builders write minimal-but-valid chain artifacts:
``manifest.json`` per iter pointing at a ``run_output_iter_NNN.json``
that satisfies ``HyperparamTuningOutput``. This keeps the tests
predicate-equivalent to the runtime contract — anything the inspector
calls "COMMITTED" must also pass ``core.resume._validate_run_output``.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from scripts import inspect_run_state as ins

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _minimal_run_output(
    *, run_name: str, model_type: str, best_score: float = -1.0, status_value: str = "completed"
) -> dict:
    """Smallest dict that validates against ``HyperparamTuningOutput``."""
    return {
        "run_name": run_name,
        "model_type": model_type,
        "file_index": 0,
        "status": status_value,
        "completed_rounds": 1,
        "total_attempts": 1,
        "best_exp_id": f"{model_type}_{run_name}_001",
        "best_denoising_score": best_score,
        "started_at": "2026-04-28 00:00:00",
        "finished_at": "2026-04-28 00:01:00",
    }


def _write_clean_chain_iter(
    workspace: Path, iter_idx: int, *, model_type: str = "wavenet", best_score: float = -1.0
) -> Path:
    """Write iter_NNN/manifest.json + the run_output it points at.

    Returns the iter_NNN/ Path. The manifest's ``output_path`` is an
    absolute path inside the iter dir so tests do not depend on cwd.
    """
    run_name = f"iter_{iter_idx:03d}"
    iter_dir = workspace / run_name
    iter_dir.mkdir(parents=True)
    sub = iter_dir / "iteration_001" / model_type
    sub.mkdir(parents=True)
    output_path = sub / f"run_output_{run_name}.json"
    output_path.write_text(
        json.dumps(
            _minimal_run_output(run_name=run_name, model_type=model_type, best_score=best_score)
        )
    )
    manifest = {
        "status": "completed",
        "iteration_dir": str(iter_dir),
        "output_path": str(output_path),
        "model_name": model_type,
        "best_score": best_score,
        "completed_rounds": 1,
    }
    (iter_dir / "manifest.json").write_text(json.dumps(manifest))
    return iter_dir


def _write_chain_iter_missing_manifest(workspace: Path, iter_idx: int) -> Path:
    """Create iter_NNN/ with no manifest at all (mid-launch crash)."""
    iter_dir = workspace / f"iter_{iter_idx:03d}"
    iter_dir.mkdir(parents=True)
    return iter_dir


def _write_chain_iter_failed_manifest(workspace: Path, iter_idx: int) -> Path:
    """Manifest exists but ``status != 'completed'``."""
    iter_dir = workspace / f"iter_{iter_idx:03d}"
    iter_dir.mkdir(parents=True)
    (iter_dir / "manifest.json").write_text(
        json.dumps(
            {
                "status": "failed",
                "iteration_dir": str(iter_dir),
                "output_path": str(iter_dir / "missing.json"),
                "model_name": None,
            }
        )
    )
    return iter_dir


def _write_chain_iter_malformed_manifest(workspace: Path, iter_idx: int) -> Path:
    """Manifest exists but is not valid JSON."""
    iter_dir = workspace / f"iter_{iter_idx:03d}"
    iter_dir.mkdir(parents=True)
    (iter_dir / "manifest.json").write_text("{not valid json")
    return iter_dir


def _run_main(argv: list[str]) -> tuple[int, str, str]:
    """Invoke ``ins.main(argv)`` and capture stdout/stderr/exit."""
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    with redirect_stdout(out_buf), redirect_stderr(err_buf):
        rc = ins.main(argv)
    return rc, out_buf.getvalue(), err_buf.getvalue()


# ---------------------------------------------------------------------------
# Test cases (numbered per the §3 plan)
# ---------------------------------------------------------------------------


def test_1_chain_three_clean_iters_next_iter_prints_4(tmp_path: Path) -> None:
    """3 clean iters → --next-iter prints 4, exit 0, only an int on stdout."""
    for i in (1, 2, 3):
        _write_clean_chain_iter(tmp_path, i, best_score=float(-i))

    rc, stdout, stderr = _run_main(
        [
            "--layout",
            "chain",
            "--workspace",
            str(tmp_path),
            "--next-iter",
        ]
    )

    assert rc == 0
    assert stdout.strip() == "4"
    assert stdout.strip().isdigit(), "machine view must emit nothing but the integer"
    assert stderr == ""


def test_2_chain_two_clean_one_missing_manifest_next_iter_prints_3(
    tmp_path: Path,
) -> None:
    """2 clean + 1 with missing manifest → next-iter prints 3."""
    _write_clean_chain_iter(tmp_path, 1)
    _write_clean_chain_iter(tmp_path, 2)
    _write_chain_iter_missing_manifest(tmp_path, 3)

    rc, stdout, _stderr = _run_main(
        [
            "--layout",
            "chain",
            "--workspace",
            str(tmp_path),
            "--next-iter",
        ]
    )

    assert rc == 0
    assert stdout.strip() == "3"


def test_3_chain_one_clean_one_failed_manifest_next_iter_prints_2(
    tmp_path: Path,
) -> None:
    """1 clean + 1 with status='failed' → next-iter prints 2."""
    _write_clean_chain_iter(tmp_path, 1)
    _write_chain_iter_failed_manifest(tmp_path, 2)

    rc, stdout, _stderr = _run_main(
        [
            "--layout",
            "chain",
            "--workspace",
            str(tmp_path),
            "--next-iter",
        ]
    )

    assert rc == 0
    assert stdout.strip() == "2"


def test_4_chain_one_clean_one_malformed_json_next_iter_prints_2(
    tmp_path: Path,
) -> None:
    """1 clean + 1 with malformed JSON manifest → next-iter prints 2."""
    _write_clean_chain_iter(tmp_path, 1)
    _write_chain_iter_malformed_manifest(tmp_path, 2)

    rc, stdout, _stderr = _run_main(
        [
            "--layout",
            "chain",
            "--workspace",
            str(tmp_path),
            "--next-iter",
        ]
    )

    assert rc == 0
    assert stdout.strip() == "2"


def test_5_chain_empty_workspace_next_iter_prints_1(tmp_path: Path) -> None:
    """No iter dirs at all → next-iter prints 1 (clean chain start)."""
    rc, stdout, _stderr = _run_main(
        [
            "--layout",
            "chain",
            "--workspace",
            str(tmp_path),
            "--next-iter",
        ]
    )

    assert rc == 0
    assert stdout.strip() == "1"


def test_6_chain_non_contiguous_gap_exits_nonzero(tmp_path: Path) -> None:
    """iter_001 + iter_003 with no iter_002 → refuse with non-zero exit."""
    _write_clean_chain_iter(tmp_path, 1)
    _write_clean_chain_iter(tmp_path, 3)

    rc, stdout, stderr = _run_main(
        [
            "--layout",
            "chain",
            "--workspace",
            str(tmp_path),
            "--next-iter",
        ]
    )

    assert rc != 0
    assert "iter_002" in stderr
    assert "non-contiguous" in stderr
    # Stdout must stay clean so a shell capture cannot accidentally pick up
    # a stale integer.
    assert stdout == ""


def test_7_chain_legacy_layout_guard_rejects(tmp_path: Path) -> None:
    """workflow_*.json on disk → legacy guard refuses, non-zero exit."""
    # Pattern 2 from validate_workspace_layout: workflow_*.json file.
    (tmp_path / "workflow_old_run.json").write_text("{}")

    rc, stdout, stderr = _run_main(
        [
            "--layout",
            "chain",
            "--workspace",
            str(tmp_path),
            "--next-iter",
        ]
    )

    assert rc != 0
    assert "Legacy workspace layout" in stderr
    assert stdout == ""


def test_8_run_layout_back_compat_renders_table(tmp_path: Path) -> None:
    """--layout run with the existing fixture pattern still produces a table."""
    run_name = "legacy_run"
    workspace = tmp_path / f"exploration_{run_name}" / run_name
    iter_dir = workspace / "iteration_001"
    model_dir = iter_dir / "wavenet"
    model_dir.mkdir(parents=True)
    output = model_dir / f"run_output_{run_name}.json"
    output.write_text(json.dumps(_minimal_run_output(run_name=run_name, model_type="wavenet")))

    rc, stdout, _stderr = _run_main(
        [
            "--layout",
            "run",
            "--run_dir",
            str(tmp_path),
            "--run_name",
            run_name,
        ]
    )

    assert rc == 0
    assert "Iter" in stdout and "Model" in stdout and "Status" in stdout
    assert "001" in stdout
    assert "wavenet" in stdout
    assert "COMMITTED" in stdout


def test_9_default_layout_resolves_to_run(tmp_path: Path) -> None:
    """Omitting --layout still routes through run-mode (back-compat default)."""
    run_name = "legacy_run"
    workspace = tmp_path / f"exploration_{run_name}" / run_name
    iter_dir = workspace / "iteration_001"
    model_dir = iter_dir / "wavenet"
    model_dir.mkdir(parents=True)
    output = model_dir / f"run_output_{run_name}.json"
    output.write_text(json.dumps(_minimal_run_output(run_name=run_name, model_type="wavenet")))

    rc, stdout, _stderr = _run_main(
        [
            "--run_dir",
            str(tmp_path),
            "--run_name",
            run_name,
        ]
    )

    assert rc == 0
    assert "COMMITTED" in stdout
    # If default had silently flipped to chain we'd expect either an error
    # (--workspace required) or a different output shape.
    assert "Last committed iteration:" in stdout


# ---------------------------------------------------------------------------
# Bonus coverage: human-view chain table includes Model + Best Score
# ---------------------------------------------------------------------------


def test_chain_human_view_includes_model_and_best_score(tmp_path: Path) -> None:
    """The chain-layout table must populate Model + Best Score columns
    just like the legacy table — operators reading the view should see
    enrichment from the parsed run_output, not just the manifest stub.
    """
    _write_clean_chain_iter(
        tmp_path,
        1,
        model_type="posenc_causal_dilated_stack",
        best_score=-3.221148,
    )
    _write_clean_chain_iter(
        tmp_path,
        2,
        model_type="spectral_skip_residual_stack",
        best_score=4.524,
    )

    rc, stdout, _stderr = _run_main(
        [
            "--layout",
            "chain",
            "--workspace",
            str(tmp_path),
        ]
    )

    assert rc == 0
    assert "posenc_causal_dilated_stack" in stdout
    assert "spectral_skip_residual_stack" in stdout
    # Best score formatting is f"{:.6f}" — assert the substring after the
    # leading sign so we catch both renderings.
    assert "-3.221148" in stdout
    assert "4.524000" in stdout
    assert "Last committed iter: iter_002" in stdout


# ---------------------------------------------------------------------------
# Regression: partial iter sandwiched between committed iters
# ---------------------------------------------------------------------------


def test_chain_partial_below_committed_advances_past_max_committed(
    tmp_path: Path,
) -> None:
    """[1c, 2c, 3c, 4-failed, 5c] → next-iter prints 6, NOT 4.

    Reproduces the V7 explore workspace state on 2026-04-30 (iter_005
    was a successful gated_context_dualpath_tcn round; iter_004 had been
    a partial broken iter). Old logic returned 4 (first non-COMMITTED),
    which would have caused the chain to overwrite iter_005's records
    when it advanced. New rule: any committed history → advance past
    max(committed); leave dangling broken iters alone.
    """
    _write_clean_chain_iter(tmp_path, 1)
    _write_clean_chain_iter(tmp_path, 2)
    _write_clean_chain_iter(tmp_path, 3)
    _write_chain_iter_failed_manifest(tmp_path, 4)
    _write_clean_chain_iter(tmp_path, 5, best_score=5.560566)

    rc, stdout, stderr = _run_main(
        [
            "--layout",
            "chain",
            "--workspace",
            str(tmp_path),
            "--next-iter",
        ]
    )

    assert rc == 0
    assert stdout.strip() == "6"
    # Dangling-broken warning surfaces iter_004 to stderr; stdout stays
    # clean for shell capture.
    assert "iter_004" in stderr
    assert "dangling" in stderr.lower()


def test_chain_dangling_warning_in_human_view(tmp_path: Path) -> None:
    """Human-view (no --next-iter) also prints the dangling warning to
    stderr while the table + summary go to stdout."""
    _write_clean_chain_iter(tmp_path, 1)
    _write_chain_iter_failed_manifest(tmp_path, 2)
    _write_clean_chain_iter(tmp_path, 3)

    rc, stdout, stderr = _run_main(
        [
            "--layout",
            "chain",
            "--workspace",
            str(tmp_path),
        ]
    )

    assert rc == 0
    assert "Last committed iter: iter_003" in stdout
    assert "launch iter_004 next" in stdout
    assert "iter_002" in stderr
    assert "dangling" in stderr.lower()


def test_chain_no_dangling_warning_when_partial_is_at_top(
    tmp_path: Path,
) -> None:
    """[1c, 2c, 3-failed] → no dangling warning (the partial IS the top).

    The partial isn't "dangling below a committed iter" — it's the
    natural retry frontier. Auto-resume returns 3 (committed=[1,2],
    max+1=3); no warning needed.
    """
    _write_clean_chain_iter(tmp_path, 1)
    _write_clean_chain_iter(tmp_path, 2)
    _write_chain_iter_failed_manifest(tmp_path, 3)

    rc, stdout, stderr = _run_main(
        [
            "--layout",
            "chain",
            "--workspace",
            str(tmp_path),
            "--next-iter",
        ]
    )

    assert rc == 0
    assert stdout.strip() == "3"
    assert "dangling" not in stderr.lower()


def test_chain_invalid_arg_combinations_rejected(tmp_path: Path) -> None:
    """argparse-level validation: layout mode policing.

    --next-iter without chain, run-mode without run_dir/run_name, and
    chain-mode without workspace must all exit non-zero via argparse's
    error path (which calls sys.exit(2)).
    """
    with pytest.raises(SystemExit):
        _run_main(
            [
                "--layout",
                "run",
                "--run_dir",
                str(tmp_path),
                "--run_name",
                "x",
                "--next-iter",
            ]
        )
    with pytest.raises(SystemExit):
        _run_main(["--layout", "run"])
    with pytest.raises(SystemExit):
        _run_main(["--layout", "chain"])
