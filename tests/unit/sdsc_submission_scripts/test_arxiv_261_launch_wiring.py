"""arXiv #261 — the launch layer's watchdog-policy wiring.

The launcher's tri-state flags feed ONE resolution
(``run_one_iteration.resolve_watchdog_policy`` → the core authority) whose
result is written back onto ``args`` before the single
``WorkflowLaunchConfig`` construction site and the dry-run view read them.
Each test names the defect only it catches. The core resolver's own
semantics are owned by ``tests/unit/core/test_arxiv_261_watchdog_profile.py``
— everything here stubs it and tests the WIRING.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from core.runtime_control.watchdog_profile import ResolvedWatchdogSettings

_REPO = Path(__file__).resolve().parents[3]
_ROI = _REPO / "sdsc_submission_scripts" / "run_one_iteration.py"

_spec = importlib.util.spec_from_file_location("run_one_iteration_for_261_test", _ROI)
roi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(roi)

_MINIMAL_ARGV = [
    "--workspace",
    "/tmp/ws",
    "--run_name",
    "r",
    "--start_iteration",
    "1",
]


def _parse(*extra: str):
    return roi.build_parser().parse_args([*_MINIMAL_ARGV, *extra])


def test_the_flags_parse_tri_state_with_legacy_positives_intact():
    """The defect only this catches: the argparse layer losing the
    tri-state — either the bare default stops being None (silently forcing
    OPERATOR MODE everywhere, the profile dead on arrival) or the existing
    positive flag every campaign script passes stops parsing True. Fails
    by: any of the four parses moving."""
    bare = _parse()
    assert bare.runtime_watchdog is None
    assert bare.runtime_watchdog_floor_seconds is None
    assert bare.execution_regime == "single"
    assert _parse("--runtime_watchdog").runtime_watchdog is True
    assert _parse("--no-runtime_watchdog").runtime_watchdog is False
    assert _parse("--execution_regime", "four_way_coresident").execution_regime == (
        "four_way_coresident"
    )


def test_resolution_writes_back_and_is_idempotent_with_stable_provenance(monkeypatch):
    """The defect only this catches: double resolution degrading provenance
    — after the write-back turns the tri-state into a concrete bool, a
    second call (the dry-run view resolves too) would take the OPERATOR
    branch and report "cli" for a profile-resolved launch. The cache on
    ``args`` is what prevents that lie. Fails by: the second call's
    provenance differing, or the write-back not landing on args."""
    resolved = ResolvedWatchdogSettings(
        enabled=True,
        safety_factor=3.5,
        floor_seconds=120.0,
        provenance="shipped:probe/single (device='probe', regime='single', calibrated=True)",
        profile_calibrated=True,
    )
    calls: list[dict] = []

    def fake_resolve(**kwargs):
        calls.append(kwargs)
        return resolved

    monkeypatch.setattr(roi, "resolve_watchdog_launch_settings", fake_resolve)
    args = _parse()
    first = roi.resolve_watchdog_policy(args)
    assert args.runtime_watchdog is True
    assert args.runtime_watchdog_safety_factor == 3.5
    assert args.runtime_watchdog_floor_seconds == 120.0
    second = roi.resolve_watchdog_policy(args)
    assert second is first, "the cache must return the SAME resolution object"
    assert len(calls) == 1, "the core authority must be consulted exactly once"
    assert second.provenance.startswith("shipped:"), "provenance must never degrade to 'cli'"


def test_operator_flags_reach_the_authority_verbatim(monkeypatch):
    """The defect only this catches: the wiring dropping or reordering the
    operator's explicit flags on their way to the authority (e.g. passing
    the floor as the safety factor, or losing the regime). Fails by: the
    recorded kwargs differing from the parsed flags."""
    seen: dict = {}

    def fake_resolve(**kwargs):
        seen.update(kwargs)
        return ResolvedWatchdogSettings(
            enabled=False, safety_factor=None, floor_seconds=60.0, provenance="cli"
        )

    monkeypatch.setattr(roi, "resolve_watchdog_launch_settings", fake_resolve)
    args = _parse(
        "--no-runtime_watchdog",
        "--runtime_watchdog_safety_factor",
        "2.5",
        "--runtime_watchdog_floor_seconds",
        "90",
        "--execution_regime",
        "dual_coresident",
    )
    roi.resolve_watchdog_policy(args)
    assert seen == {
        "cli_enabled": False,
        "cli_safety_factor": 2.5,
        "cli_floor_seconds": 90.0,
        "execution_regime": "dual_coresident",
    }
