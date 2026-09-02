"""Declared per-role subprocess memory ceilings, with provenance.

Step 11 C3 (R-11-5, R-11-6, F-11-3). Before this module the ceilings were
a bare ``dict[str, int]`` inside the launch path, justified only by a
prose comment. Three things were wrong with that, and this module fixes
exactly those three:

1. **No machine-readable provenance.** A run could not say what its
   ceilings derived from, and one of the derivations had gone stale
   without anyone noticing (**F-11-3**: the 60-GiB justification cited
   ``inference_single.py:325-331``, which is now argmax code).
2. **A silent fallback on a malformed override.** ``SIDERIUS_SUBPROCESS_RSS_GB=abc``
   resolved to the role default with no diagnostic, so a typo in a launch
   script produced a run that looked correctly configured and was not.
3. **No record of which ceilings a run executed under.**

What this module is NOT, stated because the roadmap draws the line
explicitly (§9.2): these are **execution-host calibration, not task
config**. They describe THIS machine's memory envelope. A ceiling must
never be derived from the task, and a resume on a differently-calibrated
host must stay legal (**R-11-6**) — which is why the run-invariants lock
records them as PROVENANCE and never compares them.

``core/sandbox_executor.py`` remains a launch CONSUMER of this module
(**R-11-11**); the declaration, the resolution ladder and the refusal
semantics live here.

The resolution ladder is exactly two layers, and a third is forbidden
(§9.3 finding 14)::

    SIDERIUS_SUBPROCESS_RSS_GB   (global integer or explicit role mapping)
        ->
    the role's declared default
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: The env override, unchanged from the pre-C3 seam. Named once.
RSS_OVERRIDE_ENV_VAR = "SIDERIUS_SUBPROCESS_RSS_GB"

SubprocessRole = Literal["training", "inference", "scoring"]


class MalformedCeilingOverride(ValueError):
    """``SIDERIUS_SUBPROCESS_RSS_GB`` was set to something unusable.

    A dedicated type because the pre-C3 behaviour — falling back to the
    role default in silence — is the failure this refusal replaces
    (**R-11-5**). An operator who sets the variable has stated an
    intention; resolving it to a different number without saying so
    produces a run whose configuration nobody can reconstruct afterwards.
    """


class RoleCeiling(BaseModel):
    """One role's declared host-memory ceiling and where it came from.

    ``derivation`` records HOW the number was arrived at, which is what
    makes a stale justification detectable instead of merely wrong:

    * ``"measured"`` — arithmetic over observed component sizes that still
      describes the path it governs;
    * ``"incident"`` — pinned by a named production incident;
    * ``"empirical_unverified"`` — the value is known to work in
      production, but its recorded derivation no longer describes the
      current code and has not been re-measured.
    """

    model_config = ConfigDict(frozen=True)

    role: SubprocessRole
    gib: int = Field(gt=0)
    #: Machine-readable, not prose: an auditor can filter on it.
    derivation: Literal["measured", "incident", "empirical_unverified"]
    #: ISO date the value was last SET or last CONFIRMED.
    set_on: str = Field(min_length=10)
    #: The execution host the value was calibrated against.
    calibrated_for: str = Field(min_length=1)
    #: Why this number, in one line. Prose is allowed HERE because it sits
    #: beside the machine-readable fields rather than instead of them.
    rationale: str = Field(min_length=1)


#: The declared calibration for this deployment.
#:
#: **These are the values the pre-C3 `_ROLE_DEFAULT_RSS_GB` resolved to**
#: — 40 / 60 / 24 — and §9.3 requires them to stay so for the TIDMAD
#: profile. C3 changes how they are declared, never what they are.
ROLE_CEILINGS: dict[str, RoleCeiling] = {
    "training": RoleCeiling(
        role="training",
        gib=40,
        derivation="measured",
        set_on="2026-04-20",
        calibrated_for="lilab RTX 5090 host, ~61.8 GiB RAM",
        rationale=(
            "CUDA static VA ~20 GiB + ~16 GiB working VRAM (weights, "
            "activations, gradients, optimizer state) + ~4 GiB for "
            "DataLoader workers, allocator-reserved VA and h5py buffers. "
            "Leaves ~21 GiB physical free, which preserves the Fix-1 "
            "intent: catch a runaway before the kernel OOM-killer wakes."
        ),
    ),
    "inference": RoleCeiling(
        role="inference",
        gib=60,
        derivation="empirical_unverified",
        set_on="2026-07-13",
        calibrated_for="lilab RTX 5090 host, ~61.8 GiB RAM",
        rationale=(
            "F-11-3: the recorded 2026-07-13 derivation — four ~1.86 GiB "
            "int8 numpy arrays held simultaneously at "
            "inference_single.py:325-331 — NO LONGER DESCRIBES THE PATH IT "
            "GOVERNS. Those lines are argmax/trace code now, the storage "
            "dtype is task-declared (_storage_dtype), and the four-array "
            "peak applies only to baseline/`fix` mode because agent-mode "
            "writes go through the D14 seam. The VALUE is retained because "
            "full-scope baseline inference is known to fail under 40 GiB "
            "(numpy._ArrayMemoryError on the fourth allocation); the "
            "ARITHMETIC is retired rather than restated, and re-measuring "
            "it is named debt. Lowering this without re-verifying "
            "full-scope baseline inference is a regression."
        ),
    ),
    "scoring": RoleCeiling(
        role="scoring",
        gib=24,
        derivation="incident",
        set_on="2026-04-20",
        calibrated_for="lilab host, CPU-only scoring path",
        rationale=(
            "CPU-only, so VA is approximately RSS. Kept at the original "
            "value because this is the exact codepath the 2026-04-20 "
            "incident hit — a global OOM-kill mid-scoring at 36.9 GB "
            "anon-RSS."
        ),
    ),
}

#: The launch path's historical view: role -> GiB. Kept as a derived
#: mapping so the consumer keeps its old shape while the declaration
#: above stays the single source of truth.
ROLE_DEFAULT_RSS_GB: dict[str, int] = {role: ceiling.gib for role, ceiling in ROLE_CEILINGS.items()}


def resolve_role_ceiling_gb(role: str, *, environ: Mapping[str, str] | None = None) -> int:
    """The effective host-RAM ceiling (GiB) for one sandboxed subprocess.

    Resolution order — exactly two layers, and **no third** (§9.3
    finding 14, R-11-5):

    1. :data:`RSS_OVERRIDE_ENV_VAR` — either one integer for every role, or
       an explicit comma-separated mapping such as
       ``training=0,inference=96,scoring=24``. The mapping remains one
       caller-owned calibration layer while allowing GPU hosts with different
       CUDA virtual-address footprints to disable or raise training without
       weakening scoring.
    2. The role's declared default from :data:`ROLE_CEILINGS`.

    Special values:

    * ``0`` — DISABLES the ceiling entirely. This is the explicit
      pre-Fix-1 escape hatch and is preserved deliberately, not
      tolerated: an operator diagnosing an allocator problem needs a way
      to take the cap off.
    * anything else that is not a non-negative integer — **REFUSED**,
      loudly. Before C3 a negative or non-numeric value fell back to the
      role default in silence, so `RSS_GB=4O` (letter O) produced a run
      that reported nothing wrong.

    Args:
        role: one of ``"training"``, ``"inference"``, ``"scoring"``.
        environ: environment mapping to read; defaults to ``os.environ``.
            Typed as ``Mapping`` rather than ``dict`` because ``os.environ``
            IS a ``Mapping`` and not a ``dict`` — pyright caught the
            narrower annotation in CI, which is the one static check this
            host cannot run (Node v10 < 14).
            An explicit parameter so a caller can resolve against a
            transported environment rather than the ambient one.

    Returns:
        The ceiling in GiB; ``0`` means "no ceiling".

    Raises:
        ValueError: unknown role.
        MalformedCeilingOverride: the override is set but unusable.
    """
    if role not in ROLE_CEILINGS:
        raise ValueError(
            f"resolve_role_ceiling_gb: unknown role {role!r}; "
            f"expected one of {sorted(ROLE_CEILINGS)}"
        )
    env = os.environ if environ is None else environ
    raw = env.get(RSS_OVERRIDE_ENV_VAR)
    if raw is None:
        return ROLE_CEILINGS[role].gib
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
            f"for role {role!r}. Set a non-negative integer, 0 to disable every role, "
            "or a complete training=N,inference=N,scoring=N mapping. "
            f"It is NOT ignored: a silently-ignored override is how a run "
            f"comes to execute under limits nobody chose."
        ) from None
    if value < 0:
        raise MalformedCeilingOverride(
            f"{RSS_OVERRIDE_ENV_VAR}={raw!r} selects a negative value for {role!r}. "
            f"Use 0 to disable the ceiling; a negative ceiling has no meaning."
        )
    return value


def calibration_provenance(*, environ: Mapping[str, str] | None = None) -> dict[str, object]:
    """What this run executed under, for the run-invariants lock (R-11-6).

    **Recorded, never equality-enforced.** Ceilings are execution-HOST
    calibration: the same scientific run resumed on a
    differently-calibrated host must remain legal, unlike a composition,
    metric or dataset-semantics change. ``RunInvariants`` therefore
    declares this field as PROVENANCE rather than leaving it merely absent
    from the canonical set — see ``RunInvariants._PROVENANCE``.

    The shape is deliberately flat and JSON-native so an auditor reading a
    lock file needs no code to interpret it.
    """
    env = os.environ if environ is None else environ
    override = env.get(RSS_OVERRIDE_ENV_VAR)
    return {
        "override_env": override,
        "roles": {
            role: {
                "gib": resolve_role_ceiling_gb(role, environ=env),
                "declared_gib": ceiling.gib,
                "derivation": ceiling.derivation,
                "set_on": ceiling.set_on,
            }
            for role, ceiling in sorted(ROLE_CEILINGS.items())
        },
    }
