"""
Phase 6.7 Commit 2 regression-guard suite for ``execute_tools.inference_single``.

Targets the two contracts introduced by Commit 2 of
``docs/phase67_infra_hardening_and_feedback_integrity.md``:

1. **Sentinel preflight (Fix 3 consumer side).**
   When the trainer-side sentinel ``_OK_<exp_id>`` is missing, inference
   must surface as ``error_training``, not ``error_inference:
   FileNotFoundError`` on the .pth path. The orchestrator pattern-matches
   the ``error_training:`` prefix to tag the failure category, so this
   test pins the exception type + message shape.

2. **Trial-mode `del` placement (Fix 2).**
   The trial-mode buffer-free block must run *before* ``create_abra_file``
   (where the audit observed ``numpy._ArrayMemoryError`` on 4/35 runs)
   and the canonical 6-name set must include both view-aliasing handles
   (``train_loader``, ``target_loader``) — they are views over
   ``all_input``/``all_target`` and a partial del leaves the underlying
   buffers reachable. The placement is structural, so this is asserted by
   AST inspection rather than runtime mocking.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from execute_tools.inference_single import _assert_training_sentinel


_INFERENCE_SOURCE = (
    Path(__file__).resolve().parents[3]
    / "execute_tools"
    / "inference_single.py"
)


# =============================================================================
# 1. Sentinel preflight — ``_assert_training_sentinel``
# =============================================================================


class TestAssertTrainingSentinel:
    """The orchestrator depends on the ``error_training:`` prefix in the
    exception message to route silent training crashes to the right
    error_category. These tests pin that contract."""

    def test_missing_sentinel_raises_error_training(self, tmp_path):
        # Simulate the post-crash state: model_path is what the trainer
        # *would* have written, but no _OK_ sibling exists.
        model_path = str(tmp_path / "exp_001.pth")
        with pytest.raises(RuntimeError) as exc_info:
            _assert_training_sentinel(model_path, "exp_001")
        msg = str(exc_info.value)
        # The orchestrator greps for this exact prefix to classify the
        # failure category — the prefix is the contract.
        assert msg.startswith("error_training:"), (
            f"Expected 'error_training:' prefix; got: {msg!r}"
        )
        # The model_path must be in the message so the operator can locate
        # the orphaned trial directory.
        assert model_path in msg

    def test_sentinel_present_returns_none(self, tmp_path):
        # Normal post-success state: trainer wrote both .pth and _OK_.
        model_path = str(tmp_path / "exp_001.pth")
        sentinel_path = tmp_path / "_OK_exp_001"
        sentinel_path.write_bytes(b"")  # zero-byte sentinel
        # Note: model_path itself does not need to exist — the helper
        # only checks for the sentinel. torch.load would fail later, but
        # that is a different (correctly tagged) error.
        result = _assert_training_sentinel(model_path, "exp_001")
        assert result is None

    def test_sentinel_path_is_sibling_of_model_path(self, tmp_path):
        # The sentinel lives beside the .pth in cached_models/, named
        # ``_OK_<exp_id>``. Pin this path convention so Commit 3's
        # producer-side write lands in the matching place.
        model_path = str(tmp_path / "cached_models" / "exp_xyz.pth")
        os.makedirs(tmp_path / "cached_models", exist_ok=True)
        with pytest.raises(RuntimeError) as exc_info:
            _assert_training_sentinel(model_path, "exp_xyz")
        # The error message names the exact path the helper checked.
        expected_sentinel = str(tmp_path / "cached_models" / "_OK_exp_xyz")
        assert expected_sentinel in str(exc_info.value)

    def test_message_includes_no_retry_language(self):
        # Negative guard against a regression toward a "retry-with-backoff"
        # loop, which the spec explicitly drops because it would mask
        # silent-crash root causes rather than fix them. Uses a fixed
        # model_path so pytest's tmp_path naming can't false-positive
        # match a forbidden substring.
        model_path = "/var/tmp/cached_models/exp_001.pth"
        with pytest.raises(RuntimeError) as exc_info:
            _assert_training_sentinel(model_path, "exp_001")
        msg = str(exc_info.value).lower()
        for forbidden in ("retry", "retrying", "backoff", "will try again"):
            assert forbidden not in msg, (
                f"Message must not promise a retry; got: {msg!r}"
            )


# =============================================================================
# 2. Trial-mode `del` placement — AST inspection
# =============================================================================


_CANONICAL_TRIAL_FREE_NAMES = {
    "train_loader",
    "target_loader",
    "all_input",
    "all_target",
    "raw_ch1",
    "raw_ch2",
}


def _parse_inference_module() -> ast.Module:
    return ast.parse(_INFERENCE_SOURCE.read_text(), filename=str(_INFERENCE_SOURCE))


def _find_trial_loop(tree: ast.Module) -> ast.For:
    """Locate the trial-mode ``for file_index_str, … in sorted(sample_set...)``
    loop body. We pin on the iterator name rather than line numbers so the
    test stays robust under ordinary refactors."""
    for node in ast.walk(tree):
        if isinstance(node, ast.For) and isinstance(node.target, ast.Tuple):
            names = [
                t.id for t in node.target.elts if isinstance(t, ast.Name)
            ]
            if names == ["file_index_str", "psd_segment_indices"]:
                return node
    raise AssertionError("Could not locate trial-mode for-loop in inference_single.py")


class TestTrialModeDelPlacement:
    """The trial-mode buffer-free block must run BEFORE ``create_abra_file``
    and must include the canonical 6-name set, mirroring normal mode."""

    def test_canonical_del_block_runs_before_create_abra_file(self):
        loop = _find_trial_loop(_parse_inference_module())

        canonical_del_idx = None
        create_call_idx = None
        for i, stmt in enumerate(loop.body):
            if isinstance(stmt, ast.Delete):
                names = {
                    t.id for t in stmt.targets if isinstance(t, ast.Name)
                }
                if _CANONICAL_TRIAL_FREE_NAMES.issubset(names):
                    canonical_del_idx = i
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                func = stmt.value.func
                if isinstance(func, ast.Name) and func.id == "create_abra_file":
                    create_call_idx = i

        assert canonical_del_idx is not None, (
            f"No `del` statement freeing the canonical trial-mode set "
            f"{sorted(_CANONICAL_TRIAL_FREE_NAMES)} was found in the trial "
            f"loop body."
        )
        assert create_call_idx is not None, (
            "create_abra_file call not found in trial loop body — refactor "
            "may have moved it; update this test."
        )
        assert canonical_del_idx < create_call_idx, (
            f"Trial-mode buffer-free block runs at body index "
            f"{canonical_del_idx} but create_abra_file is at index "
            f"{create_call_idx}. The free MUST come first — that is the "
            f"whole point of Phase 6.7 Fix 2."
        )

    def test_canonical_del_includes_view_aliasing_handles(self):
        # Pin the regression: a partial `del` that omits train_loader /
        # target_loader leaves the underlying all_input/all_target arrays
        # reachable through the views, defeating the gc.collect().
        loop = _find_trial_loop(_parse_inference_module())
        for stmt in loop.body:
            if isinstance(stmt, ast.Delete):
                names = {
                    t.id for t in stmt.targets if isinstance(t, ast.Name)
                }
                if _CANONICAL_TRIAL_FREE_NAMES.issubset(names):
                    # The set must include BOTH view handles, not just the
                    # owners. (Owners alone are insufficient — the views
                    # keep the buffer alive otherwise.)
                    assert "train_loader" in names
                    assert "target_loader" in names
                    return
        raise AssertionError(
            "Canonical trial-mode del block not found — see "
            "test_canonical_del_block_runs_before_create_abra_file for "
            "expected name set."
        )

    def test_gc_collect_follows_canonical_del(self):
        # gc.collect() must be called after the canonical del to actually
        # release the buffers (CPython doesn't run gen-2 collection on
        # every del; large numpy buffers can stay reachable in the gc
        # roots until the next collection cycle).
        loop = _find_trial_loop(_parse_inference_module())
        body = loop.body
        canonical_del_idx = None
        for i, stmt in enumerate(body):
            if isinstance(stmt, ast.Delete):
                names = {
                    t.id for t in stmt.targets if isinstance(t, ast.Name)
                }
                if _CANONICAL_TRIAL_FREE_NAMES.issubset(names):
                    canonical_del_idx = i
                    break
        assert canonical_del_idx is not None
        # The very next statement should be gc.collect().
        next_stmt = body[canonical_del_idx + 1]
        assert isinstance(next_stmt, ast.Expr)
        call = next_stmt.value
        assert isinstance(call, ast.Call)
        assert isinstance(call.func, ast.Attribute)
        assert call.func.attr == "collect"
        assert isinstance(call.func.value, ast.Name)
        assert call.func.value.id == "gc"
