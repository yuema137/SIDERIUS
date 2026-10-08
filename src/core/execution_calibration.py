"""Caller-declared subprocess address-space caps; absent values inherit the OS.

SIDERIUS_SUBPROCESS_RSS_GB retains its historical name, but configures RLIMIT_AS,
not resident RAM. The existing integer/complete-role-mapping parser is the sole
configuration authority. No task, hardware or execution-host limit is inferred.
Resolved declarations are provenance only, not canonical resume requirements.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

RSS_OVERRIDE_ENV_VAR = "SIDERIUS_SUBPROCESS_RSS_GB"
SubprocessRole = Literal["training", "inference", "scoring"]


class MalformedCeilingOverride(ValueError):
    """An explicitly configured address-space limit is unusable; never fall back."""


class RoleCeiling(BaseModel):
    """One role's additional RLIMIT_AS declaration, not a measured OS limit.

    None records an omitted declaration. Explicit zero records an operator's
    choice to add no cap. Both preserve inherited OS soft/hard restrictions.
    Positive values retain the existing child setter behavior.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: SubprocessRole
    gib: int | None = Field(default=None, ge=0)
    source: Literal["environment", "inherited_os"] = "inherited_os"

    @model_validator(mode="after")
    def source_matches_declaration(self):
        if (self.gib is None) != (self.source == "inherited_os"):
            raise ValueError("Only an omitted declaration uses inherited_os provenance")
        return self


# Compatibility-shaped views, derived from the single supported-role vocabulary.
# These declare inheritance; they are not per-machine calibration records.
ROLE_CEILINGS: dict[str, RoleCeiling] = {
    role: RoleCeiling(role=role) for role in get_args(SubprocessRole)
}
ROLE_DEFAULT_RSS_GB: dict[str, int | None] = {
    role: ceiling.gib for role, ceiling in ROLE_CEILINGS.items()
}


def resolve_role_ceiling(role: str, *, environ: Mapping[str, str] | None = None) -> RoleCeiling:
    """Resolve one role without reading or changing OS limits.

    Accept one nonnegative integer or a complete unique role mapping. The parser
    validates the selected role's numeric value, preserving its existing behavior;
    provenance resolves all roles and therefore validates every selected value.
    An explicitly supplied environment excludes ambient configuration. Empty,
    malformed, negative and incomplete declarations refuse, never fall back.
    """
    if role not in ROLE_CEILINGS:
        raise ValueError(
            f"resolve_role_ceiling_gb: unknown role {role!r}; "
            f"expected one of {sorted(ROLE_CEILINGS)}"
        )
    env = os.environ if environ is None else environ
    raw = env.get(RSS_OVERRIDE_ENV_VAR)
    if raw is None:
        return ROLE_CEILINGS[role]
    selected = raw
    if "=" in raw:
        values: dict[str, str] = {}
        for item in raw.split(","):
            key, separator, value = item.partition("=")
            key = key.strip()
            value = value.strip()
            if separator != "=" or key not in ROLE_CEILINGS or not value or key in values:
                raise MalformedCeilingOverride(
                    f"{RSS_OVERRIDE_ENV_VAR}={raw!r} is not a complete unique role mapping. "
                    "Use one non-negative integer, or "
                    "training=N,inference=N,scoring=N with every role present."
                )
            values[key] = value
        if set(values) != set(ROLE_CEILINGS):
            raise MalformedCeilingOverride(
                f"{RSS_OVERRIDE_ENV_VAR}={raw!r} must name exactly "
                f"{sorted(ROLE_CEILINGS)}; got {sorted(values)}."
            )
        selected = values[role]
    try:
        value = int(selected)
    except ValueError:
        raise MalformedCeilingOverride(
            f"{RSS_OVERRIDE_ENV_VAR}={raw!r} is not an integer number of GiB "
            f"for role {role!r}. Set a non-negative integer, 0 to add no extra cap, "
            "or a complete training=N,inference=N,scoring=N mapping. "
            f"It is NOT ignored: a silently-ignored override is how a run "
            f"comes to execute under limits nobody chose."
        ) from None
    if value < 0:
        raise MalformedCeilingOverride(
            f"{RSS_OVERRIDE_ENV_VAR}={raw!r} selects a negative value for {role!r}. "
            f"Use 0 to add no extra cap; a negative ceiling has no meaning."
        )
    return RoleCeiling(role=ROLE_CEILINGS[role].role, gib=value, source="environment")


def resolve_role_ceiling_gb(role: str, *, environ: Mapping[str, str] | None = None) -> int | None:
    """Compatibility projection: None inherits OS, zero installs no extra cap."""
    return resolve_role_ceiling(role, environ=environ).gib


def calibration_provenance(*, environ: Mapping[str, str] | None = None) -> dict[str, object]:
    """Record configured address-space policy, never measured OS limits.

    RunInvariants keeps this JSON-native field noncanonical. Existing records
    remain readable; a changed host policy does not prohibit resume. Only the
    named override is recorded, never the complete environment.
    """
    env = os.environ if environ is None else environ
    return {
        "override_env": env.get(RSS_OVERRIDE_ENV_VAR),
        "limit_kind": "RLIMIT_AS",
        "unit": "GiB",
        "roles": {
            role: resolve_role_ceiling(role, environ=env).model_dump(exclude={"role"})
            for role in sorted(ROLE_CEILINGS)
        },
    }
