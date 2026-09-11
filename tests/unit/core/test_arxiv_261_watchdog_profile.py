"""arXiv #261 / Q-07c-6 — the device-profiled watchdog policy authority.

Operator ruling (2026-08-25): the watchdog mechanism is generic; its numbers
are configuration keyed by ``(device class, execution regime)``, resolved by
ONE authority (``core/runtime_control/watchdog_profile.py``) reusing the
existing per-device calibration-dir machinery. No borrowed numbers for an
uncalibrated pair; no device-name conditionals in framework logic. Each test
below names the defect only it catches.
"""

from __future__ import annotations

import ast
import json
import textwrap
from pathlib import Path

import pytest

from agent.skills.evaluate_time_skill.calibration import gpu_slug
from core.runtime_control.watchdog_profile import (
    MalformedRuntimeProfile,
    resolve_runtime_profile,
    resolve_watchdog_launch_settings,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

RTX_5090 = "NVIDIA GeForce RTX 5090"
H100 = "NVIDIA H100 80GB HBM3"


@pytest.fixture()
def empty_overlay_dir(tmp_path, monkeypatch):
    """Point the calibration dir at an empty tmp dir, so only the SHIPPED
    layer answers — a developer machine's real measured overlay must never
    leak into these assertions."""
    monkeypatch.setenv("SIDERIUS_CALIBRATION_DIR", str(tmp_path))
    return tmp_path


def test_framework_ships_no_device_specific_profile(empty_overlay_dir):
    """A deployment profile must not become an implicit framework default."""
    profile = resolve_runtime_profile(RTX_5090, "single")
    assert profile.calibrated is False
    assert profile.watchdog_enabled is False
    assert profile.watchdog_safety_factor is None
    assert profile.watchdog_floor_seconds == 60.0
    assert profile.provenance == "uncalibrated"


def test_unknown_pair_resolves_the_explicit_uncalibrated_state(empty_overlay_dir):
    """THE ruling's core clause — the defect only this catches: an unknown
    (device, regime) pair acquiring invented or borrowed numbers (the exact
    failure that produced Q-07c-6's INCONCLUSIVE watchdog kills). H100 /
    four_way_coresident is deliberately unshipped until qualification
    measures it. Fails by: any value other than the honest legacy-off
    triple, or ``calibrated`` claiming True."""
    profile = resolve_runtime_profile(H100, "four_way_coresident")
    assert profile.calibrated is False
    assert profile.watchdog_enabled is False
    assert profile.watchdog_safety_factor is None
    assert profile.watchdog_floor_seconds == 60.0
    assert profile.provenance == "uncalibrated"


def test_borrowing_across_regimes_is_impossible_by_construction(tmp_path, monkeypatch):
    """The defect only this catches: the resolver keying on device alone, so
    5090/single's calibrated numbers silently apply to a 5090 co-resident
    fleet (cross-REGIME borrowing — same device, different topology).
    Fails by: the four-way pair resolving calibrated."""
    monkeypatch.setenv("SIDERIUS_CALIBRATION_DIR", str(tmp_path))
    overlay = tmp_path / f"runtime_profiles_{gpu_slug(RTX_5090)}.json"
    overlay.write_text(
        json.dumps(
            {
                "profiles": {
                    f"{gpu_slug(RTX_5090)}/single": {
                        "watchdog_enabled": True,
                        "watchdog_safety_factor": 2.0,
                        "watchdog_floor_seconds": 90.0,
                    }
                }
            }
        )
    )
    assert resolve_runtime_profile(RTX_5090, "single").calibrated is True
    quad = resolve_runtime_profile(RTX_5090, "four_way_coresident")
    assert quad.calibrated is False
    assert quad.watchdog_enabled is False


def test_measured_overlay_outranks_shipped(tmp_path, monkeypatch):
    """The defect only this catches: precedence inversion — the shipped
    default silently winning over an on-box measurement, which would make
    qualification's written overlay a no-op. Fails by: the shipped 3.5/120
    row answering instead of the overlay's values."""
    monkeypatch.setenv("SIDERIUS_CALIBRATION_DIR", str(tmp_path))
    overlay = tmp_path / f"runtime_profiles_{gpu_slug(RTX_5090)}.json"
    overlay.write_text(
        json.dumps(
            {
                "profiles": {
                    f"{gpu_slug(RTX_5090)}/single": {
                        "watchdog_enabled": True,
                        "watchdog_safety_factor": 2.0,
                        "watchdog_floor_seconds": 90.0,
                    }
                }
            }
        )
    )
    profile = resolve_runtime_profile(RTX_5090, "single")
    assert profile.watchdog_safety_factor == 2.0
    assert profile.watchdog_floor_seconds == 90.0
    assert profile.calibrated is True
    assert profile.provenance == f"measured:{overlay}"


def test_malformed_sources_refuse_loudly(tmp_path, monkeypatch):
    """The execution-calibration precedent — the defect only this catches: a
    malformed overlay or a typo'd row key silently ignored while the
    operator believes it is in force. Fails by: resolution succeeding (a
    quiet fallback) or raising anything but the named error."""
    monkeypatch.setenv("SIDERIUS_CALIBRATION_DIR", str(tmp_path))
    overlay = tmp_path / f"runtime_profiles_{gpu_slug(RTX_5090)}.json"

    overlay.write_text("{not json")
    with pytest.raises(MalformedRuntimeProfile, match="does not parse"):
        resolve_runtime_profile(RTX_5090, "single")

    overlay.write_text(json.dumps({"profiles": "not-a-mapping"}))
    with pytest.raises(MalformedRuntimeProfile, match="'profiles:' mapping"):
        resolve_runtime_profile(RTX_5090, "single")

    overlay.write_text(
        json.dumps(
            {
                "profiles": {
                    f"{gpu_slug(RTX_5090)}/single": {
                        "watchdog_enabled": True,
                        "watchdog_saftey_factor": 2.0,  # the typo the guard exists for
                    }
                }
            }
        )
    )
    with pytest.raises(MalformedRuntimeProfile, match="malformed"):
        resolve_runtime_profile(RTX_5090, "single")


def test_flags_always_win_and_are_never_profile_polluted(empty_overlay_dir):
    """The defect only this catches: the launch layer consulting the profile
    OVER an explicit operator decision — either direction. An explicit
    ``--no-runtime_watchdog`` on a calibrated-on device must stay off; an
    explicit on must not inherit profile numbers it did not ask for (legacy
    behavior byte-identical: safety None, floor 60). Fails by: profile
    values leaking into OPERATOR MODE."""
    forced_off = resolve_watchdog_launch_settings(
        cli_enabled=False,
        cli_safety_factor=None,
        cli_floor_seconds=None,
        execution_regime="single",
        device_name=RTX_5090,
    )
    assert forced_off.enabled is False
    assert forced_off.provenance == "cli"
    assert forced_off.profile_calibrated is None

    forced_on = resolve_watchdog_launch_settings(
        cli_enabled=True,
        cli_safety_factor=None,
        cli_floor_seconds=None,
        execution_regime="single",
        device_name=RTX_5090,
    )
    assert forced_on.enabled is True
    assert forced_on.safety_factor is None, "legacy semantics: admission-factor fallback downstream"
    assert forced_on.floor_seconds == 60.0


def test_profile_mode_uncalibrated_reproduces_legacy_bare_launch_exactly(empty_overlay_dir):
    """The behavioral-parity pin — the defect only this catches: the
    uncalibrated PROFILE MODE drifting from the pre-#261 bare-launch triple
    (disabled / None / 60.0), which would change every bare launch on every
    unprofiled machine. Fails by: any of the three values moving."""
    resolved = resolve_watchdog_launch_settings(
        cli_enabled=None,
        cli_safety_factor=None,
        cli_floor_seconds=None,
        execution_regime="four_way_coresident",
        device_name=H100,
    )
    assert resolved.enabled is False
    assert resolved.safety_factor is None
    assert resolved.floor_seconds == 60.0
    assert resolved.profile_calibrated is False


def test_profile_mode_calibrated_applies_the_profile_with_field_overrides(tmp_path, monkeypatch):
    """The defect only this catches: PROFILE MODE ignoring a lone
    field-level flag (an operator pinning just the floor while letting the
    profile decide enablement must get exactly that composition). Fails by:
    the profile floor overriding the explicit one, or the profile's
    enablement/safety not applying."""
    monkeypatch.setenv("SIDERIUS_CALIBRATION_DIR", str(tmp_path))
    overlay = tmp_path / f"runtime_profiles_{gpu_slug(RTX_5090)}.json"
    overlay.write_text(
        json.dumps(
            {
                "profiles": {
                    f"{gpu_slug(RTX_5090)}/single": {
                        "watchdog_enabled": True,
                        "watchdog_safety_factor": 2.5,
                        "watchdog_floor_seconds": 90.0,
                    }
                }
            }
        )
    )
    resolved = resolve_watchdog_launch_settings(
        cli_enabled=None,
        cli_safety_factor=None,
        cli_floor_seconds=200.0,
        execution_regime="single",
        device_name=RTX_5090,
    )
    assert resolved.enabled is True
    assert resolved.safety_factor == 2.5
    assert resolved.floor_seconds == 200.0
    assert resolved.profile_calibrated is True
    assert resolved.provenance.startswith("measured:")


# ---------------------------------------------------------------------------
# Census — one authority, no device conditionals (ruling §1/§2)
# ---------------------------------------------------------------------------

#: Every production root, execute_tools included (the F-12bc-9 lesson: a
#: census whose FILE SET omits a directory is green for the wrong reason).
_PRODUCTION_ROOTS = (
    "src/core",
    "src/agent",
    "src/execute_tools",
    "src/nodes",
    "src/workflows",
    "scripts",
)

_DEVICE_TOKENS = ("h100", "5090", "a100", "rtx")


def _device_conditional_sites(tree: ast.AST) -> list[int]:
    """Line numbers of ``if``/comparison tests whose CODE (not comments or
    docstrings — AST sees neither) compares against a device-name literal."""
    sites: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            for sub in ast.walk(node.test):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    lowered = sub.value.lower()
                    if any(tok in lowered for tok in _DEVICE_TOKENS):
                        sites.append(node.lineno)
    return sites


def test_no_device_name_conditionals_in_production_logic():
    """The ruling's §2 ban, executable — the defect only this catches: an
    ``if "h100" ...`` (any device token) branch entering generic framework
    logic, the pattern the profile authority exists to make unnecessary.
    AST-based, so the module docstrings that legitimately DISCUSS the ban
    cannot false-positive. Fails by: naming file:line of the branch."""
    offenders: list[str] = []
    for root in _PRODUCTION_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            offenders.extend(
                f"{path.relative_to(REPO_ROOT)}:{line}" for line in _device_conditional_sites(tree)
            )
    assert not offenders, (
        "device-name conditional(s) in production logic — the runtime-profile "
        f"authority owns device facts (#261): {offenders}"
    )


def test_the_census_can_see_a_device_conditional_negative_control():
    """The anti-decoration leg (census-blindness family): the sweep itself
    must FIRE on the banned shape, or the positive census is green for the
    wrong reason. Fails by: the synthetic offender not being detected."""
    snippet = textwrap.dedent(
        """
        def f(device_name: str) -> int:
            if "H100" in device_name:
                return 1
            return 0
        """
    )
    assert _device_conditional_sites(ast.parse(snippet)) == [3]


def test_one_resolution_authority_for_runtime_profiles():
    """The §3 no-second-system clause — the defect only this catches: a
    parallel reader of ``configs/runtime_profiles.yaml`` (or a second
    module re-implementing profile resolution) appearing outside the one
    authority. The allowlist is exact: the authority itself, and the launch
    layer that IMPORTS it (whose flag help/banner may name the config path
    for discoverability). Fails by: naming the new file."""
    allowed = {
        Path("src/core/runtime_control/watchdog_profile.py"),
        Path("sdsc_submission_scripts/run_one_iteration.py"),
    }
    mentions: set[Path] = set()
    for root in (*_PRODUCTION_ROOTS, "sdsc_submission_scripts"):
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            if "runtime_profiles" in path.read_text(encoding="utf-8"):
                mentions.add(path.relative_to(REPO_ROOT))
    assert mentions <= allowed, (
        f"unexpected runtime-profile reader(s) {sorted(str(p) for p in mentions - allowed)} — "
        "core/runtime_control/watchdog_profile.py is the ONE authority (#261)"
    )
    assert Path("src/core/runtime_control/watchdog_profile.py") in mentions, (
        "the census lost sight of the authority itself — its file set is broken"
    )
