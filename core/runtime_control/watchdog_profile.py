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

A THIRD state exists beside those two layers (**F-H100-WD-1-PRETAG**,
operator-ruled Route B): a run may DECLARE a :class:`RequiredProfileBinding`
— the ``<gpu_slug>/<regime>`` key it requires plus the sha256 of the
measured-overlay file certified for it. A declared binding FAILS CLOSED:
wrong hardware/regime, a missing or divergent overlay, or a verified
overlay lacking the required row all raise
:class:`RequiredProfileBindingError` instead of falling back — the run does
not start. UNDECLARED (``required_binding=None``) keeps the legacy
fail-open-to-outer-budget behavior above byte-identical. The binding is the
MECHANISM only; campaign values (H100 rows, measured numbers) are post-tag
qualification data recorded in the overlay, never shipped here.

Explicit operator flags always override the profile — an override is a
recorded launch decision, not a hidden fallback. Device identity comes from
the existing authority, ``core.hardware_context.discover()`` (CPU fallback
included), never from a parallel probe. A declared REQUIRED binding is the
one exception: combining it with an explicit enablement flag is a
contradiction (the flag would bypass the very resolution the binding
certifies) and refuses loudly — see
:func:`resolve_watchdog_launch_settings`.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

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


class RequiredProfileBindingError(ValueError):
    """A run DECLARED a required runtime profile and it cannot be certified.

    The fail-CLOSED counterpart of the honest UNCALIBRATED state
    (**F-H100-WD-1-PRETAG**, operator-ruled Route B). UNCALIBRATED fails
    open on purpose — watchdog off, the outer wall-time budgets bound the
    run — which is the right posture for exploratory work and exactly the
    wrong one for a formal campaign that certified its numbers: there, a
    missing or divergent overlay must STOP the launch, never degrade it
    silently. Raised when the discovered ``(device, regime)`` is not the
    declared one, when the bound overlay is missing or does not hash to the
    declared sha256, or when the verified overlay lacks the required row.
    The run does not start. The declared digest comes from a prior
    qualification run's recorded provenance (e.g. the overlay sha captured
    on the qualified host), so certification is against evidence, never
    memory.
    """


class RequiredProfileBinding(BaseModel):
    """A declared, certifiable identity for the profile a run REQUIRES.

    The ``core/execution_calibration.py`` precedent: a declared value
    carries machine-readable provenance and is REFUSED when it cannot be
    honored — never silently substituted. Here the declaration is the pair
    (which profile, which exact overlay bytes): the launch layer states
    both up front, and resolution certifies both or raises
    :class:`RequiredProfileBindingError`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    profile_key: str = Field(
        min_length=3,
        description="The declared profile identity, '<gpu_slug>/<regime>' "
        "exactly as _profile_key produces (e.g. copied from a prior "
        "qualification run's recorded provenance). Resolution refuses when "
        "the DISCOVERED pair differs — wrong hardware or regime is a "
        "refusal, not a fallback.",
    )
    expected_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="sha256 hex digest of the measured-overlay FILE bytes "
        "certified for this run. Hashed over the exact bytes parsed "
        "(single read, never re-opened), so the profile consumed is "
        "provably the one the operator qualified.",
    )

    @field_validator("profile_key")
    @classmethod
    def _profile_key_is_slug_slash_regime(cls, value: str) -> str:
        if "/" not in value:
            raise ValueError(
                f"profile_key {value!r} is not of the form '<gpu_slug>/<regime>' "
                f"(the exact shape _profile_key produces)"
            )
        return value


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
        "'measured:<path>', 'bound:<path>#sha256=<hex>', or 'uncalibrated'."
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


def _load_bound_overlay(path: str, binding: RequiredProfileBinding) -> tuple[dict[str, Any], str]:
    """Read, certify and parse a REQUIRED overlay from ONE read of the file.

    TOCTOU-safe by construction (operator rule: hash THE EXACT BYTES
    PARSED): the file is read exactly once with ``Path.read_bytes``; the
    sha256 is computed over that bytes object and ``json.loads`` parses the
    SAME object — never a re-open, so no window exists in which a swapped
    file is hashed as one content and parsed as another.

    Returns:
        ``(profiles mapping, sha256 hexdigest of the verified bytes)``.

    Raises:
        RequiredProfileBindingError: the file is missing/unreadable, or its
            digest is not ``binding.expected_sha256`` (both digests named).
        MalformedRuntimeProfile: the VERIFIED bytes do not parse or lack the
            'profiles:' mapping (mirrors ``_load_measured``).
    """
    try:
        data = Path(path).read_bytes()
    except FileNotFoundError:
        raise RequiredProfileBindingError(
            f"required runtime-profile binding {binding.profile_key!r} cannot be "
            f"certified: the measured overlay at {path} does not exist. A REQUIRED "
            f"binding never falls back to shipped or uncalibrated — the run does "
            f"not start."
        ) from None
    except OSError as exc:
        raise RequiredProfileBindingError(
            f"required runtime-profile binding {binding.profile_key!r} cannot be "
            f"certified: the measured overlay at {path} is unreadable: {exc}"
        ) from exc
    digest = hashlib.sha256(data).hexdigest()
    if digest != binding.expected_sha256:
        raise RequiredProfileBindingError(
            f"required runtime-profile binding {binding.profile_key!r} cannot be "
            f"certified: the overlay at {path} hashes to sha256={digest}, but the "
            f"binding declares sha256={binding.expected_sha256}. The file is not "
            f"the one that was certified — refuse, never resolve from it."
        )
    try:
        raw = json.loads(data)
    except json.JSONDecodeError as exc:
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
    return profiles, digest


def _profile_key(device_name: str, execution_regime: str) -> str:
    return f"{gpu_slug(device_name)}/{execution_regime}"


def resolve_runtime_profile(
    device_name: str,
    execution_regime: str,
    *,
    required_binding: RequiredProfileBinding | None = None,
) -> RuntimeProfile:
    """The ONE resolution: measured overlay > shipped defaults > UNCALIBRATED.

    Precedence mirrors the execution-calibration two-layer rule: a value
    measured ON THIS MACHINE outranks the shipped default; an unknown pair
    resolves to the explicit uncalibrated profile rather than any invented
    or borrowed number.

    With ``required_binding`` DECLARED the ladder is replaced by fail-closed
    certification (**F-H100-WD-1-PRETAG**): the discovered
    ``<gpu_slug>/<regime>`` key must equal the declared one, the measured
    overlay must hash to the declared sha256 (single read — the exact bytes
    parsed), and the verified overlay must carry the required row. Any miss
    raises :class:`RequiredProfileBindingError`; there is no fall-through
    to shipped or uncalibrated. ``required_binding=None`` keeps the ladder
    above byte-identical.
    """
    key = _profile_key(device_name, execution_regime)

    if required_binding is not None:
        if key != required_binding.profile_key:
            raise RequiredProfileBindingError(
                f"required runtime-profile binding declares "
                f"{required_binding.profile_key!r}, but this launch discovered "
                f"{key!r} (device={device_name!r}, regime={execution_regime!r}). "
                f"Wrong hardware or regime is a refusal, not a fallback."
            )
        path = _measured_overlay_path(device_name)
        profiles, digest = _load_bound_overlay(path, required_binding)
        if key not in profiles:
            raise RequiredProfileBindingError(
                f"required runtime-profile binding {key!r} cannot be certified: "
                f"the verified overlay at {path} (sha256={digest}) does not carry "
                f"that row. A verified overlay LACKING the required profile "
                f"refuses — it never falls through to shipped or uncalibrated."
            )
        entry = _validate_entry(profiles[key], key=key, source=path)
        return RuntimeProfile(
            device_name=device_name,
            execution_regime=execution_regime,
            calibrated=True,
            provenance=f"bound:{path}#sha256={digest}",
            **entry.model_dump(),
        )

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
    required_binding: RequiredProfileBinding | None = None,
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

    REQUIRED BINDING (``required_binding`` declared, **F-H100-WD-1-PRETAG**):
    PROFILE MODE resolves through the fail-closed certification in
    :func:`resolve_runtime_profile` — e.g. a formal campaign pinning the
    overlay sha captured on its qualification host. Combining a binding
    with an explicit
    enablement flag REFUSES loudly: OPERATOR MODE never consults the
    profile, so a declared REQUIRED binding would be silently unenforced —
    exactly the fail-open this mechanism removes. Field-level
    ``cli_safety_factor``/``cli_floor_seconds`` overrides in PROFILE MODE
    remain legal: the binding governs WHICH profile is consumed, not the
    recorded per-field launch overrides.

    ``device_name=None`` probes through ``core.hardware_context.discover()``
    (the existing identity authority; CPU fallback built in).
    """
    if required_binding is not None and cli_enabled is not None:
        raise RequiredProfileBindingError(
            f"a required runtime-profile binding ({required_binding.profile_key!r}) "
            f"was declared together with an explicit watchdog enablement flag "
            f"(cli_enabled={cli_enabled!r}). OPERATOR MODE bypasses profile "
            f"resolution entirely, so the declared requirement would be silently "
            f"unenforced — drop the enablement flag (field-level factor/floor "
            f"overrides stay legal in PROFILE MODE) or drop the binding."
        )
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

    profile = resolve_runtime_profile(
        device_name, execution_regime, required_binding=required_binding
    )
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
