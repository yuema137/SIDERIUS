"""Device-profiled runtime/watchdog policy — ONE resolution authority.

Operator ruling (#261 / Q-07c-6, 2026-08-25): the watchdog mechanism stays
generic; the NUMBERS (enabled, safety factor, floor) are configuration keyed
by ``(device class, execution regime)``. No device-name conditional may
appear in production logic — a launcher, Gate, or preflight asks THIS module
and applies what it returns.

Two layers, reusing the repository's existing by-device machinery rather
than inventing a second system:

1. **Shipped defaults** — ``configs/runtime_profiles.yaml``: the committed,
   reviewed profiles (today: the RTX 5090 single-chain posture, calibrated
   on the lilab RTX 5090 across the V19/V20 campaigns). Declarative data,
   like the task-health configs.
2. **Measured overlay** — ``runtime_profiles_<gpu_slug>.json`` in the SAME
   per-device calibration directory the time estimator already owns
   (``$SIDERIUS_CALIBRATION_DIR``, default ``~/.siderius`` — see
   ``agent/skills/evaluate_time_skill/calibration.py``). This is where an
   H100 qualification RECORDS what it measures; returning to a 5090 later
   selects the 5090 profile with no re-tuning, because device calibration
   is persistent configuration data, not a mutable global.

CALIBRATED vs UNCALIBRATED is explicit. An unknown ``(device, regime)`` pair
resolves to the honest UNCALIBRATED profile: watchdog DISABLED — never
borrowed numbers, never a magic constant (Q-07c-6's INCONCLUSIVE watchdog
kills are what borrowing produces) — with ``calibrated=False`` and
provenance saying so. The runaway bound for an uncalibrated run is the OUTER
wall-time budget the launch already carries
(``--trial/--formal_time_budget_minutes``); qualification runs under that
bound until it measures real values and writes the overlay.

Explicit operator flags always override the profile — an override is a
recorded launch decision, not a hidden fallback. Device identity comes from
the existing authority, ``core.hardware_context.discover()`` (CPU fallback
included), never from a parallel probe.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent.skills.evaluate_time_skill.calibration import calibration_dir, gpu_slug

#: The committed defaults. Relative to the repository root (derived from this
#: file's location — never the caller's cwd).
_REPO_ROOT = Path(__file__).resolve().parents[2]
SHIPPED_PROFILES_PATH = _REPO_ROOT / "configs" / "runtime_profiles.yaml"

ExecutionRegime = Literal["single", "dual_coresident", "four_way_coresident"]

#: The legacy launch defaults a profile-less resolution must reproduce
#: byte-for-byte (run_one_iteration.py's pre-#261 argparse defaults).
_LEGACY_FLOOR_SECONDS = 60.0


class MalformedRuntimeProfile(ValueError):
    """A profile source exists but does not parse/validate — refuse loudly.

    The execution-calibration precedent: a malformed override must never be
    silently ignored, because the operator believes it is in force.
    """


class _ProfileEntry(BaseModel):
    """The on-disk shape of one profile row (shipped YAML or measured JSON)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    watchdog_enabled: bool
    watchdog_safety_factor: float | None = None
    watchdog_floor_seconds: float = _LEGACY_FLOOR_SECONDS


class RuntimeProfile(BaseModel):
    """The resolved watchdog/runtime policy for one (device, regime) pair."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    device_name: str
    execution_regime: str
    calibrated: bool = Field(
        description="True only when a shipped or measured profile matched. "
        "False = the honest UNCALIBRATED state: watchdog disabled, outer "
        "budgets are the runaway bound."
    )
    watchdog_enabled: bool
    watchdog_safety_factor: float | None = Field(
        default=None, description="None when the watchdog is disabled."
    )
    watchdog_floor_seconds: float = _LEGACY_FLOOR_SECONDS
    provenance: str = Field(
        description="Where these values came from: 'shipped:<key>', "
        "'measured:<path>', or 'uncalibrated'."
    )


class ResolvedWatchdogSettings(BaseModel):
    """What the launch layer actually applies, with recorded provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool
    safety_factor: float | None
    floor_seconds: float
    provenance: str
    profile_calibrated: bool | None = Field(
        default=None,
        description="PROFILE MODE only: whether the consulted (device, "
        "regime) profile was calibrated. None when operator flags decided "
        "and the profile was never consulted.",
    )


def _measured_overlay_path(device_name: str) -> str:
    return os.path.join(calibration_dir(), f"runtime_profiles_{gpu_slug(device_name)}.json")


def _validate_entry(raw: Any, *, key: str, source: str) -> _ProfileEntry:
    if not isinstance(raw, dict):
        raise MalformedRuntimeProfile(
            f"runtime profile '{key}' in {source} must be a mapping; got {type(raw).__name__}."
        )
    try:
        return _ProfileEntry.model_validate(raw)
    except ValidationError as exc:
        raise MalformedRuntimeProfile(
            f"runtime profile '{key}' in {source} is malformed — fix or remove "
            f"it, it is never silently ignored: {exc}"
        ) from exc


def _load_shipped() -> dict[str, Any]:
    if not SHIPPED_PROFILES_PATH.exists():
        return {}
    try:
        raw = yaml.safe_load(SHIPPED_PROFILES_PATH.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise MalformedRuntimeProfile(
            f"shipped runtime profiles at {SHIPPED_PROFILES_PATH} do not parse: {exc}"
        ) from exc
    profiles = raw.get("profiles")
    if not isinstance(profiles, dict):
        raise MalformedRuntimeProfile(
            f"shipped runtime profiles at {SHIPPED_PROFILES_PATH} must carry a "
            f"'profiles:' mapping; got {type(profiles).__name__}."
        )
    return profiles


def _load_measured(device_name: str) -> dict[str, Any]:
    path = _measured_overlay_path(device_name)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise MalformedRuntimeProfile(
            f"measured runtime-profile overlay at {path} does not parse: {exc}. "
            "Fix or remove it — a malformed overlay is never silently ignored."
        ) from exc
    profiles = raw.get("profiles")
    if not isinstance(profiles, dict):
        raise MalformedRuntimeProfile(
            f"measured runtime-profile overlay at {path} must carry a "
            f"'profiles:' mapping; got {type(profiles).__name__}."
        )
    return profiles


def _profile_key(device_name: str, execution_regime: str) -> str:
    return f"{gpu_slug(device_name)}/{execution_regime}"


def resolve_runtime_profile(device_name: str, execution_regime: str) -> RuntimeProfile:
    """The ONE resolution: measured overlay > shipped defaults > UNCALIBRATED.

    Precedence mirrors the execution-calibration two-layer rule: a value
    measured ON THIS MACHINE outranks the shipped default; an unknown pair
    resolves to the explicit uncalibrated profile rather than any invented
    or borrowed number.
    """
    key = _profile_key(device_name, execution_regime)

    measured = _load_measured(device_name)
    if key in measured:
        source = _measured_overlay_path(device_name)
        entry = _validate_entry(measured[key], key=key, source=source)
        return RuntimeProfile(
            device_name=device_name,
            execution_regime=execution_regime,
            calibrated=True,
            provenance=f"measured:{source}",
            **entry.model_dump(),
        )

    shipped = _load_shipped()
    if key in shipped:
        entry = _validate_entry(shipped[key], key=key, source=str(SHIPPED_PROFILES_PATH))
        return RuntimeProfile(
            device_name=device_name,
            execution_regime=execution_regime,
            calibrated=True,
            provenance=f"shipped:{key}",
            **entry.model_dump(),
        )

    return RuntimeProfile(
        device_name=device_name,
        execution_regime=execution_regime,
        calibrated=False,
        watchdog_enabled=False,
        watchdog_safety_factor=None,
        watchdog_floor_seconds=_LEGACY_FLOOR_SECONDS,
        provenance="uncalibrated",
    )


def resolve_watchdog_launch_settings(
    *,
    cli_enabled: bool | None,
    cli_safety_factor: float | None,
    cli_floor_seconds: float | None,
    execution_regime: str,
    device_name: str | None = None,
) -> ResolvedWatchdogSettings:
    """Merge operator flags with the device profile — flags always win.

    OPERATOR MODE (``cli_enabled`` is not ``None`` — ``--runtime_watchdog``
    or ``--no_runtime_watchdog`` was passed): the profile is NOT consulted;
    behavior is byte-identical to the pre-#261 launch layer (safety factor
    stays ``None`` unless given → the watchdog falls back to the
    phase-effective admission factor downstream; floor defaults to 60.0).
    Every existing launch script passes explicit flags, so none changes.

    PROFILE MODE (no enablement flag): the ``(device, regime)`` profile
    decides. A field-level flag still overrides that field. An uncalibrated
    pair yields exactly the legacy bare-launch defaults (disabled / None /
    60.0), so the only behavioral delta anywhere is a bare launch on a pair
    that HAS a calibrated profile.

    ``device_name=None`` probes through ``core.hardware_context.discover()``
    (the existing identity authority; CPU fallback built in).
    """
    if cli_enabled is not None:
        return ResolvedWatchdogSettings(
            enabled=cli_enabled,
            safety_factor=cli_safety_factor,
            floor_seconds=(
                cli_floor_seconds if cli_floor_seconds is not None else _LEGACY_FLOOR_SECONDS
            ),
            provenance="cli",
        )

    if device_name is None:
        from core.hardware_context import discover

        device_name = discover().device_name

    profile = resolve_runtime_profile(device_name, execution_regime)
    return ResolvedWatchdogSettings(
        enabled=profile.watchdog_enabled,
        safety_factor=(
            cli_safety_factor if cli_safety_factor is not None else profile.watchdog_safety_factor
        ),
        floor_seconds=(
            cli_floor_seconds if cli_floor_seconds is not None else profile.watchdog_floor_seconds
        ),
        provenance=f"{profile.provenance} (device={device_name!r}, regime={execution_regime!r}, "
        f"calibrated={profile.calibrated})",
        profile_calibrated=profile.calibrated,
    )
