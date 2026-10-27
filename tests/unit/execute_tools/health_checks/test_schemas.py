"""Health context path resolution, callable serialization and gate action behavior.

Plain schema declarations and completed migration inventories are not retested.
"""

from __future__ import annotations

from execute_tools.health_checks.schemas import (
    GateAction,
    GateResult,
    HealthCheckContext,
)


class TestHealthCheckContext:
    def test_get_denoised_path_prefers_explicit(self):
        """When a file_index is in denoised_paths, it wins over the callable."""
        ctx = HealthCheckContext(
            model_name="m",
            run_name="r",
            round_index=1,
            denoised_paths={0: "explicit.h5"},
            denoised_filename_fn=lambda fi: f"lazy_{fi:04d}.h5",
        )
        assert ctx.get_denoised_path(0) == "explicit.h5"

    def test_get_denoised_path_falls_back_to_callable(self):
        """Callable fills the gaps when no explicit path exists for an index."""
        ctx = HealthCheckContext(
            model_name="m",
            run_name="r",
            round_index=1,
            denoised_filename_fn=lambda fi: f"lazy_{fi:04d}.h5",
        )
        assert ctx.get_denoised_path(7) == "lazy_0007.h5"

    def test_get_denoised_path_returns_none_when_neither(self):
        ctx = HealthCheckContext(model_name="m", run_name="r", round_index=1)
        assert ctx.get_denoised_path(0) is None

    def test_callable_excluded_from_json(self):
        """denoised_filename_fn is a Callable — not JSON-serialisable, and
        the context is a within-process transport, never persisted. Must
        be excluded from model_dump."""
        ctx = HealthCheckContext(
            model_name="m",
            run_name="r",
            round_index=1,
            denoised_filename_fn=lambda fi: "x.h5",
        )
        dumped = ctx.model_dump()
        assert "denoised_filename_fn" not in dumped


class TestGateResult:
    def _make(self, action: GateAction, passed: bool = True) -> GateResult:
        return GateResult(
            gate_id="g1",
            round_index=1,
            passed=passed,
            action=action,
        )

    def test_should_invalidate_round(self):
        """The surviving routing flag (the skip properties were retired
        with their enum members, F-SCANC-1)."""
        gr = self._make(GateAction.INVALIDATE_ROUND, passed=False)
        assert gr.should_invalidate_round is True

    def test_continue_action_has_no_should_flag(self):
        gr = self._make(GateAction.CONTINUE, passed=True)
        assert gr.should_invalidate_round is False
