"""S2 / U6 (#256) — the nested implementation-attempt layout authority."""

from __future__ import annotations

import os

import pytest

from execute_tools.impl_attempts import (
    impl_attempt_dir,
    impl_attempt_dirname,
    list_impl_attempt_dirs,
    stage_artifact_dir,
    terminal_impl_attempt_dir,
)


def test_dirname_is_zero_padded_and_one_based():
    """DEFECT: an unpadded name (``impl_10`` < ``impl_2`` lexically) or a
    zero-based index would make "terminal" pick the wrong retry."""
    assert impl_attempt_dirname(1) == "impl_001"
    assert impl_attempt_dirname(12) == "impl_012"
    with pytest.raises(ValueError):
        impl_attempt_dirname(0)


def test_discovery_orders_by_index_and_ignores_everything_else(tmp_path):
    """DEFECT: listing order or a loose prefix match (``impl_x``, a FILE
    named impl_004) would let a stray entry become the terminal attempt."""
    for name in ("impl_002", "impl_010", "impl_001", "models", "impl_x"):
        (tmp_path / name).mkdir()
    (tmp_path / "impl_004").write_text("a file, not a directory")
    dirs = list_impl_attempt_dirs(str(tmp_path))
    assert [os.path.basename(d) for d in dirs] == ["impl_001", "impl_002", "impl_010"]
    assert terminal_impl_attempt_dir(str(tmp_path)) == str(tmp_path / "impl_010")
    assert impl_attempt_dir(str(tmp_path), 3) == str(tmp_path / "impl_003")


def test_a_pre_u6_attempt_dir_resolves_to_itself(tmp_path):
    """COMPATIBILITY: historical workspaces keep the implementor/validation
    records at the attempt level; a reader must find them there. Fails if
    the fallback is dropped (None, or a never-created impl_001)."""
    (tmp_path / "implementor_r1.json").write_text("{}")
    assert terminal_impl_attempt_dir(str(tmp_path)) is None
    assert stage_artifact_dir(str(tmp_path)) == str(tmp_path)
    assert stage_artifact_dir(str(tmp_path / "absent")) == str(tmp_path / "absent")


def test_both_readers_resolve_the_stage_directory_through_the_authority():
    """REACHABILITY: ``funnel_assembly`` and ``workflow_validation`` must
    both CALL ``stage_artifact_dir`` — a reader that rebuilds the path by
    hand reads the attempt level and silently misses every nested retry.
    Checked per AST call node, never by substring."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[3] / "src/execute_tools"
    for module in ("funnel_assembly.py", "workflow_validation.py"):
        tree = ast.parse((root / module).read_text(encoding="utf-8"))
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and (getattr(node.func, "id", None) or getattr(node.func, "attr", None))
            == "stage_artifact_dir"
        ]
        assert calls, f"{module} does not resolve the stage directory through the authority"
