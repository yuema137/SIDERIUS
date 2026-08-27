"""arXiv #261 — the launch layer's watchdog-policy wiring.

The launcher's tri-state flags feed ONE resolution
(``run_one_iteration.resolve_watchdog_policy`` → the core authority) whose
result is written back onto ``args`` before the single
``WorkflowLaunchConfig`` construction site and the dry-run view read them.
Each test names the defect only it catches. The core resolver's own
semantics are owned by ``tests/unit/core/test_arxiv_261_watchdog_profile.py``
— everything here stubs it and tests the WIRING.

F-PROFILE-WIRE-1 adds the DECLARATION half of that wiring (the
``TestRequiredProfileDeclaration`` class below). Those tests deliberately do
NOT stub the resolver: the defect they exist for is that a declared binding
never reached it, and a stub cannot see an argument the production call
never passes. They drive the real argparse and the real authority against a
real overlay file in a per-test calibration directory.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from agent.skills.evaluate_time_skill.calibration import gpu_slug
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
    recorded kwargs differing from the parsed flags.

    The ``required_binding`` key is asserted here too, pinned to ``None``:
    an equality assertion over the WHOLE kwarg mapping is what makes a
    silently-added or silently-dropped authority argument visible."""
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
        "required_binding": None,
    }


# ---------------------------------------------------------------------------
# F-PROFILE-WIRE-1 — the DECLARATION path.
#
# #339 landed RequiredProfileBinding as a fail-closed mechanism, but nothing
# could declare one: resolve_watchdog_launch_settings took `required_binding`
# keyword-only and the sole production call site never passed it. The
# mechanism was implemented and structurally unreachable, so M4's exact-tag
# "Gold overlay reachability and effective consumption" proof would have
# failed by construction.
# ---------------------------------------------------------------------------

#: The device these tests pin. Hardcoded rather than probed: the resolution
#: key is '<gpu_slug>/<regime>', and a test that asked the host what GPU it
#: has would pass on one machine and skip on another.
_DEVICE = "NVIDIA H100 80GB HBM3"
_REGIME = "single"

#: The values the overlay declares. Hardcoded, and deliberately DIFFERENT
#: from both the legacy bare-launch defaults (disabled/None/60.0) and any
#: shipped row, so "these came from the certified overlay" is unambiguous.
_OVERLAY_ENABLED = True
_OVERLAY_SAFETY_FACTOR = 4.25
_OVERLAY_FLOOR_SECONDS = 180.0


def _write_overlay(calibration_dir: Path) -> tuple[Path, str, str]:
    """Write a measured overlay for ``_DEVICE``; return (path, key, sha256).

    The digest is computed over the exact bytes written, which is what the
    binding certifies.
    """
    key = f"{gpu_slug(_DEVICE)}/{_REGIME}"
    payload = json.dumps(
        {
            "profiles": {
                key: {
                    "watchdog_enabled": _OVERLAY_ENABLED,
                    "watchdog_safety_factor": _OVERLAY_SAFETY_FACTOR,
                    "watchdog_floor_seconds": _OVERLAY_FLOOR_SECONDS,
                }
            }
        }
    ).encode("utf-8")
    path = calibration_dir / f"runtime_profiles_{gpu_slug(_DEVICE)}.json"
    path.write_bytes(payload)
    return path, key, hashlib.sha256(payload).hexdigest()


@pytest.fixture
def calib(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the calibration directory at a per-test tmp dir, and make
    device discovery deterministic.

    Both are required for the resolution to be reproducible: the overlay
    path is ``$SIDERIUS_CALIBRATION_DIR/runtime_profiles_<slug>.json`` and
    the slug comes from the discovered device.
    """
    d = tmp_path / "calib"
    d.mkdir()
    monkeypatch.setenv("SIDERIUS_CALIBRATION_DIR", str(d))

    class _Ctx:
        device_name = _DEVICE

    monkeypatch.setattr("core.hardware_context.discover", lambda: _Ctx())
    return d


class TestRequiredProfileDeclaration:
    """Witness (a) reachability, (b) fail-closed, (c) undeclared identity."""

    def test_a_declared_binding_reaches_the_authority_and_certifies_the_overlay(self, calib: Path):
        """(a) The defect only this catches: the declaration flags parsing
        into a Namespace that nothing forwards — exactly #339's state, where
        the mechanism existed and `required_binding` was never passed.

        Certification is proven by PROVENANCE, not by the values: an
        undeclared launch on this same host resolves the same numbers off
        the same overlay (see the sibling test), so equal numbers prove
        nothing. Only the 'bound:' prefix and the echoed digest prove
        `_load_bound_overlay` actually ran.

        Fails by: provenance staying 'measured:'/'shipped:'/'uncalibrated'
        (the binding never reached resolution), or the digest not being the
        one declared."""
        path, key, sha = _write_overlay(calib)
        args = _parse(
            "--required_runtime_profile_path",
            str(path),
            "--required_runtime_profile",
            key,
            "--required_runtime_profile_sha256",
            sha,
        )
        resolved = roi.resolve_watchdog_policy(args)

        assert resolved.provenance.startswith("bound:"), (
            "a declared binding must resolve through fail-closed certification; "
            f"provenance was {resolved.provenance!r}"
        )
        assert f"#sha256={sha}" in resolved.provenance
        assert resolved.enabled is _OVERLAY_ENABLED
        assert resolved.safety_factor == _OVERLAY_SAFETY_FACTOR
        assert resolved.floor_seconds == _OVERLAY_FLOOR_SECONDS
        # The write-back the rest of the launch layer reads.
        assert args.runtime_watchdog is _OVERLAY_ENABLED
        assert args.runtime_watchdog_floor_seconds == _OVERLAY_FLOOR_SECONDS

    def test_a2_the_declaration_changes_the_outcome_on_identical_on_disk_state(self, calib: Path):
        """(a) The defect only this catches: threading that is present but
        inert. With ONE on-disk state, declaring a digest that does not match
        must REFUSE while declaring nothing must SUCCEED. A resolver that
        ignored the binding would resolve both identically.

        Fails by: the declared case resolving instead of refusing."""
        path, key, sha = _write_overlay(calib)
        wrong = "0" * 64
        assert wrong != sha

        undeclared = roi.resolve_watchdog_policy(_parse())
        assert undeclared.provenance.startswith("measured:")
        assert undeclared.enabled is _OVERLAY_ENABLED

        with pytest.raises(SystemExit):
            roi.resolve_watchdog_policy(
                _parse(
                    "--required_runtime_profile_path",
                    str(path),
                    "--required_runtime_profile",
                    key,
                    "--required_runtime_profile_sha256",
                    wrong,
                )
            )

    def test_b_declared_but_missing_overlay_refuses_naming_the_flag(self, calib: Path):
        """(b) The defect only this catches: a declared requirement falling
        back to the shipped/uncalibrated ladder when the qualification
        overlay is absent — the run would start, exit 0, and be watchdogged
        by numbers nobody certified.

        Fails by: no SystemExit, or a refusal that does not name the flag
        (an operator reading the log must know WHICH declaration failed)."""
        key = f"{gpu_slug(_DEVICE)}/{_REGIME}"
        absent = calib / "qualification" / "runtime_profiles.json"
        # deliberately no artifact written at the declared path
        with pytest.raises(SystemExit) as excinfo:
            roi.resolve_watchdog_policy(
                _parse(
                    "--required_runtime_profile_path",
                    str(absent),
                    "--required_runtime_profile",
                    key,
                    "--required_runtime_profile_sha256",
                    "a" * 64,
                )
            )
        message = str(excinfo.value)
        assert "--required_runtime_profile" in message
        assert "does not exist" in message

    def test_b_declared_with_a_mismatched_digest_refuses_naming_both_digests(self, calib: Path):
        """(b) The defect only this catches: certifying against a file that
        is present but is NOT the qualified one — an overlay edited or
        regenerated after qualification. The refusal must name both digests,
        because 'the hash is wrong' without them is undiagnosable.

        Fails by: resolving anyway, or a message missing either digest."""
        path, key, sha = _write_overlay(calib)
        declared = "b" * 64
        with pytest.raises(SystemExit) as excinfo:
            roi.resolve_watchdog_policy(
                _parse(
                    "--required_runtime_profile_path",
                    str(path),
                    "--required_runtime_profile",
                    key,
                    "--required_runtime_profile_sha256",
                    declared,
                )
            )
        message = str(excinfo.value)
        assert "--required_runtime_profile" in message
        assert declared in message, "the refusal must quote the DECLARED digest"
        assert sha in message, "the refusal must quote the ACTUAL digest"

    def test_b_a_partial_declaration_refuses_instead_of_resolving_as_undeclared(self, calib: Path):
        """(b) The defect only this catches: a SUBSET of the three flags being
        silently treated as no declaration. That is the fail-OPEN this whole
        mechanism removes — the operator believes a profile is pinned while
        the legacy ladder quietly decides.

        Every proper non-empty subset is exercised, not just the singletons:
        the two-flag cases are the ones that look most like a complete
        declaration, and (key, sha256) without a path is exactly the shape
        that shipped before the artifact path was required.

        Fails by: any proper subset parsing through to a resolution, or a
        refusal that does not name the flags that are missing."""
        path, key, sha = _write_overlay(calib)
        full = {
            "--required_runtime_profile_path": str(path),
            "--required_runtime_profile": key,
            "--required_runtime_profile_sha256": sha,
        }
        flags = sorted(full)
        subsets = [
            [flags[0]],
            [flags[1]],
            [flags[2]],
            [flags[0], flags[1]],
            [flags[0], flags[2]],
            [flags[1], flags[2]],
        ]
        for subset in subsets:
            argv: list[str] = []
            for flag in subset:
                argv += [flag, full[flag]]
            with pytest.raises(SystemExit) as excinfo:
                roi.resolve_watchdog_policy(_parse(*argv))
            message = str(excinfo.value)
            for missing in (f for f in flags if f not in subset):
                assert missing in message, (
                    f"the refusal for {subset} must name the missing {missing}, "
                    f"so the operator learns what to add"
                )

    @pytest.mark.parametrize(
        ("cli_flags", "regime"),
        [
            ((), "single"),
            ((), "dual_coresident"),
            (("--runtime_watchdog",), "single"),
            (("--no-runtime_watchdog",), "single"),
            (("--runtime_watchdog", "--runtime_watchdog_safety_factor", "3.5"), "single"),
            (("--runtime_watchdog_floor_seconds", "120"), "four_way_coresident"),
            (
                (
                    "--no-runtime_watchdog",
                    "--runtime_watchdog_safety_factor",
                    "2.5",
                    "--runtime_watchdog_floor_seconds",
                    "90",
                ),
                "dual_coresident",
            ),
        ],
    )
    def test_c_undeclared_launches_resolve_exactly_as_before(
        self, calib: Path, cli_flags: tuple[str, ...], regime: str
    ):
        """(c) The defect only this catches: the declaration path altering
        launches that declare nothing — every existing campaign, Gate and
        queue runner. This is the load-bearing compatibility property.

        The differential reference is the PRE-CHANGE call: this PR does not
        modify ``watchdog_profile.py`` at all, so invoking the authority with
        exactly the four kwargs the old body passed reproduces pre-change
        behaviour by construction. The comparison is therefore between the
        new wiring and the old wiring's literal arguments, not between a
        function and itself.

        Fails by: `resolve_watchdog_policy` passing a non-None binding for a
        flagless launch, or the new flags perturbing any resolved field."""
        _write_overlay(calib)
        argv = (*cli_flags, "--execution_regime", regime)

        args = _parse(*argv)
        now = roi.resolve_watchdog_policy(args)

        pristine_args = _parse(*argv)
        before = roi.resolve_watchdog_launch_settings(
            cli_enabled=pristine_args.runtime_watchdog,
            cli_safety_factor=pristine_args.runtime_watchdog_safety_factor,
            cli_floor_seconds=pristine_args.runtime_watchdog_floor_seconds,
            execution_regime=pristine_args.execution_regime,
        )
        assert now.model_dump() == before.model_dump()

    def test_c_anchor_a_flagless_uncalibrated_launch_keeps_the_legacy_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """(c) The differential above compares two live calls, so a change
        that moved BOTH would slip through. This anchors the undeclared
        uncalibrated outcome to hardcoded literals.

        Fails by: the legacy bare-launch triple (disabled / None / 60.0)
        moving for a launch that declares nothing."""
        monkeypatch.setenv("SIDERIUS_CALIBRATION_DIR", str(tmp_path))

        class _Ctx:
            device_name = "A Device No Profile Row Describes"

        monkeypatch.setattr("core.hardware_context.discover", lambda: _Ctx())

        resolved = roi.resolve_watchdog_policy(_parse())
        assert resolved.enabled is False
        assert resolved.safety_factor is None
        assert resolved.floor_seconds == 60.0
        assert resolved.provenance.startswith("uncalibrated")
