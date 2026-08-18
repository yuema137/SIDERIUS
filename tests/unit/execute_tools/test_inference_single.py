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

import h5py
import numpy as np
import pytest

from execute_tools.inference_single import (
    _assert_training_sentinel,
    _is_complete_trial_output,
)

_INFERENCE_SOURCE = Path(__file__).resolve().parents[3] / "execute_tools" / "inference_single.py"


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
        assert msg.startswith("error_training:"), f"Expected 'error_training:' prefix; got: {msg!r}"
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
            assert forbidden not in msg, f"Message must not promise a retry; got: {msg!r}"


class TestCompleteTrialOutput:
    """Interrupted inference may reuse only fully flushed ABRA outputs."""

    @staticmethod
    def _write(path: Path, channel1: np.ndarray, channel2: np.ndarray) -> None:
        with h5py.File(path, "w") as handle:
            timeseries = handle.create_group("timeseries")
            timeseries.create_group("channel0001").create_dataset("timeseries", data=channel1)
            timeseries.create_group("channel0002").create_dataset("timeseries", data=channel2)

    def test_accepts_exact_readable_int8_channels(self, tmp_path):
        path = tmp_path / "complete.h5"
        values = np.arange(8, dtype=np.int8)
        self._write(path, values, values)

        assert _is_complete_trial_output(str(path), expected_samples=8)

    @pytest.mark.parametrize(
        ("channel1", "channel2", "expected_samples"),
        [
            (np.arange(7, dtype=np.int8), np.arange(8, dtype=np.int8), 8),
            (np.arange(8, dtype=np.int16), np.arange(8, dtype=np.int8), 8),
        ],
    )
    def test_rejects_wrong_shape_or_dtype(self, tmp_path, channel1, channel2, expected_samples):
        path = tmp_path / "invalid.h5"
        self._write(path, channel1, channel2)

        assert not _is_complete_trial_output(str(path), expected_samples=expected_samples)

    def test_rejects_missing_or_unreadable_file(self, tmp_path):
        assert not _is_complete_trial_output(str(tmp_path / "missing.h5"), expected_samples=8)


# =============================================================================
# 2. Trial-mode `del` placement — AST inspection
# =============================================================================


_CANONICAL_TRIAL_FREE_NAMES = {
    "train_loader",
    "target_loader",
    "all_input",
    "all_target",
    "input_chunks",
    "target_chunks",
}


def _parse_inference_module() -> ast.Module:
    return ast.parse(_INFERENCE_SOURCE.read_text(), filename=str(_INFERENCE_SOURCE))


def _find_trial_loop(tree: ast.Module) -> ast.For:
    """Locate the trial-mode ``for file_index_str, … in sorted(sample_set...)``
    loop body. We pin on the iterator name rather than line numbers so the
    test stays robust under ordinary refactors."""
    for node in ast.walk(tree):
        if isinstance(node, ast.For) and isinstance(node.target, ast.Tuple):
            names = [t.id for t in node.target.elts if isinstance(t, ast.Name)]
            if names == ["file_index_str", "psd_segment_indices"]:
                return node
    raise AssertionError("Could not locate trial-mode for-loop in inference_single.py")


class TestTrialModeDelPlacement:
    """The trial-mode buffer-free block must run BEFORE the deliverable write
    and must include the canonical 6-name set, mirroring normal mode.

    D14-1 C4: the write is the seam call ``data_path.write_deliverable(...)``
    (which performs the flatten/astype copies create_abra_file used to make
    inline), so the detector matches that call — inside or outside a ``with``
    block — while the protected property (free BEFORE write) is unchanged.
    """

    @staticmethod
    def _is_deliverable_write(stmt: ast.stmt) -> bool:
        candidates: list[ast.stmt] = [stmt]
        if isinstance(stmt, ast.With):
            candidates = list(stmt.body)
        for inner in candidates:
            if isinstance(inner, ast.Expr) and isinstance(inner.value, ast.Call):
                func = inner.value.func
                if isinstance(func, ast.Name) and func.id == "create_abra_file":
                    return True
                if isinstance(func, ast.Attribute) and func.attr == "write_deliverable":
                    return True
        return False

    def test_canonical_del_block_runs_before_deliverable_write(self):
        loop = _find_trial_loop(_parse_inference_module())

        canonical_del_idx = None
        write_call_idx = None
        for i, stmt in enumerate(loop.body):
            if isinstance(stmt, ast.Delete):
                names = {t.id for t in stmt.targets if isinstance(t, ast.Name)}
                if _CANONICAL_TRIAL_FREE_NAMES.issubset(names):
                    canonical_del_idx = i
            if self._is_deliverable_write(stmt):
                write_call_idx = i

        assert canonical_del_idx is not None, (
            f"No `del` statement freeing the canonical trial-mode set "
            f"{sorted(_CANONICAL_TRIAL_FREE_NAMES)} was found in the trial "
            f"loop body."
        )
        assert write_call_idx is not None, (
            "Deliverable write (write_deliverable / create_abra_file) not "
            "found in trial loop body — refactor may have moved it; update "
            "this test."
        )
        assert canonical_del_idx < write_call_idx, (
            f"Trial-mode buffer-free block runs at body index "
            f"{canonical_del_idx} but the deliverable write is at index "
            f"{write_call_idx}. The free MUST come first — that is the "
            f"whole point of Phase 6.7 Fix 2."
        )

    def test_canonical_del_includes_view_aliasing_handles(self):
        # Pin the regression: a partial `del` that omits train_loader /
        # target_loader leaves the underlying all_input/all_target arrays
        # reachable through the views, defeating the gc.collect().
        loop = _find_trial_loop(_parse_inference_module())
        for stmt in loop.body:
            if isinstance(stmt, ast.Delete):
                names = {t.id for t in stmt.targets if isinstance(t, ast.Name)}
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
                names = {t.id for t in stmt.targets if isinstance(t, ast.Name)}
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


# =============================================================================
# 3. Trial-mode per-file timing instrumentation — AST inspection
# =============================================================================
#
# Pin the structural contract introduced by Commit B of
# docs/refine_inference_time_estimator.md: trial-mode emits per-file timings
# to a sidecar JSON when ``--timing_out_json`` is set, so the parent process
# can decompose subprocess wall-time into ``process_startup_ms`` (Python +
# CUDA + torch.load — paid once) and ``per_file_elapsed_ms`` (scales with
# eval volume). Without this separation the gate amortises a fixed cost over
# trial's tiny denominator and over-predicts formal-round time.


def _function_def(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Could not locate function {name!r} in inference_single.py")


class TestTimingFlagAndInstrumentation:
    """Commit B contract: ``--timing_out_json`` plumbing + per-file timing
    accumulation in the trial loop. AST-level so we don't need to spin up a
    real torch + h5py subprocess; the parent-side wiring is exercised
    separately in tests/unit/core/test_sandbox_executor.py."""

    def test_timing_out_json_flag_registered(self):
        """``get_parser`` must expose ``--timing_out_json`` so the parent's
        ``cmd.extend([...])`` doesn't get rejected as unrecognised."""
        get_parser = _function_def(_parse_inference_module(), "get_parser")
        flags: set[str] = set()
        for node in ast.walk(get_parser):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                flags.add(node.args[0].value)
        assert "--timing_out_json" in flags, (
            f"get_parser is missing --timing_out_json; current flags: {sorted(flags)}"
        )

    def test_trial_loop_brackets_each_iteration_with_perf_counter(self):
        """Each iteration must record ``time.perf_counter()`` at the start
        and compute ``elapsed_ms`` near the end. This is the per-file
        timing that the parent sums into ``process_startup_ms``."""
        loop = _find_trial_loop(_parse_inference_module())
        perf_counter_calls = [
            node
            for node in ast.walk(loop)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "perf_counter"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "time"
        ]
        assert len(perf_counter_calls) >= 2, (
            f"Expected at least 2 time.perf_counter() calls in trial loop "
            f"(start + end of each iteration); found {len(perf_counter_calls)}"
        )

    def test_per_file_timings_list_appended(self):
        """The trial loop must append a dict with ``file_index``,
        ``n_psd_segs``, and ``elapsed_ms`` keys to the per-file accumulator
        — those are the three columns the aggregator (Commit C) reads."""
        loop = _find_trial_loop(_parse_inference_module())
        for node in ast.walk(loop):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "append"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "per_file_timings_ms"
                and node.args
                and isinstance(node.args[0], ast.Dict)
            ):
                keys = {k.value for k in node.args[0].keys if isinstance(k, ast.Constant)}
                assert {"file_index", "n_psd_segs", "elapsed_ms"}.issubset(keys), (
                    f"per_file_timings_ms.append payload missing required keys; got: {sorted(keys)}"
                )
                return
        raise AssertionError("No per_file_timings_ms.append({...}) call found in trial loop")

    def test_sidecar_written_when_flag_set(self):
        """After the loop, ``args.timing_out_json`` must gate a JSON dump
        of the accumulator. The parent reads this file back; if the gate is
        missing or the wrong variable is dumped, the parent silently sees
        an empty list and falls back to the constant ratio."""
        tree = _parse_inference_module()
        # The write block is inside ``main`` after the trial loop. We walk
        # main's body looking for `if args.timing_out_json:` followed by a
        # `json.dump(per_file_timings_ms, ...)` call.
        main_fn = _function_def(tree, "main")
        found = False
        for node in ast.walk(main_fn):
            if not isinstance(node, ast.If):
                continue
            test = node.test
            if not (
                isinstance(test, ast.Attribute)
                and test.attr == "timing_out_json"
                and isinstance(test.value, ast.Name)
                and test.value.id == "args"
            ):
                continue
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "dump"
                    and isinstance(inner.func.value, ast.Name)
                    and inner.func.value.id == "json"
                    and inner.args
                    and isinstance(inner.args[0], ast.Name)
                    and inner.args[0].id == "per_file_timings_ms"
                ):
                    found = True
                    break
            if found:
                break
        assert found, (
            "Expected `if args.timing_out_json: ... json.dump(per_file_timings_ms, ...)` "
            "block in main(); not found."
        )
