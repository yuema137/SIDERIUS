"""HealthCheckContext.target_path_fn + get_target_path() tests (M8 §3.4).

The target-path field lets checks read a CH2-style ground-truth HDF5
without hardcoding task-specific paths. Recording-only checks must
degrade gracefully when the field is absent — this file covers both
paths.
"""

from __future__ import annotations

from execute_tools.health_checks.schemas import HealthCheckContext


def _ctx(**overrides) -> HealthCheckContext:
    base = {
        "model_name": "wavenet",
        "run_name": "test_run",
        "round_index": 1,
    }
    base.update(overrides)
    return HealthCheckContext(**base)


class TestGetTargetPath:
    def test_returns_none_when_target_path_fn_absent(self):
        """Default None → get_target_path returns None without raising.

        Required for recording-only checks to degrade gracefully in
        pseudo-mode / stub contexts where no target file exists.
        """
        ctx = _ctx()
        assert ctx.target_path_fn is None
        assert ctx.get_target_path(0) is None
        assert ctx.get_target_path(19) is None

    def test_calls_target_path_fn_when_present(self):
        """Callable is invoked with the file_index and its result returned verbatim."""
        called_with: list[int] = []

        def fake_fn(idx: int) -> str:
            called_with.append(idx)
            return f"/data/target_{idx:04d}.h5"

        ctx = _ctx(target_path_fn=fake_fn)
        assert ctx.get_target_path(5) == "/data/target_0005.h5"
        assert ctx.get_target_path(19) == "/data/target_0019.h5"
        assert called_with == [5, 19]

    def test_target_path_fn_excluded_from_serialisation(self):
        """Callables cannot round-trip through JSON; the field is
        ``exclude=True`` so model_dump / model_dump_json omit it."""
        ctx = _ctx(target_path_fn=lambda i: f"/x/{i}.h5")
        dumped = ctx.model_dump()
        assert "target_path_fn" not in dumped
        # model_dump_json must also succeed without raising
        _ = ctx.model_dump_json()
