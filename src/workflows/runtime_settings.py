"""Resolve the standard launch's runtime flags without importing its runner.

Resolution reads runtime profiles and may discover hardware through the core
owner. It mutates/caches parsed arguments as the launcher historically did;
importing this module does not resolve settings or start execution.
"""

from __future__ import annotations

import argparse

from core.runtime_control.validation_limits import validate_phase_deadline
from core.runtime_control.watchdog_profile import (
    RequiredProfileBinding,
    RequiredProfileBindingError,
    ResolvedWatchdogSettings,
    resolve_watchdog_launch_settings,
)


def build_required_profile_binding(
    args: argparse.Namespace,
) -> RequiredProfileBinding | None:
    """F-H100-WD-1-PRETAG — turn the declaration flags into a typed binding.

    The declaration is the TRIPLE ``(which artifact, which profile, which
    exact bytes)``; no part means anything alone. A partial declaration is
    therefore REFUSED rather than resolved as undeclared: silently ignoring
    ``--required_runtime_profile`` because its digest was forgotten is
    exactly the fail-open this mechanism exists to remove — the operator
    would believe a requirement is in force while the legacy
    measured > shipped > uncalibrated ladder quietly decides.

    The PATH is part of the declaration and not derived, which is what
    closes ``finding_1_invisible_default``: while the artifact was located
    by the ordinary discovery rule, a binding certified what was found but
    never that the right file was consulted.

    Returns:
        The validated binding, or ``None`` when NO flag was passed — in
        which case resolution keeps the legacy ladder byte-identically.

    Raises:
        SystemExit: some but not all three flags were passed, or the
            declared values are not a valid ``RequiredProfileBinding`` (a
            relative artifact path, a bad key shape, or a digest that is not
            64 lowercase hex characters).
    """
    from pydantic import ValidationError

    declared = {
        "--required_runtime_profile_path": args.required_runtime_profile_path,
        "--required_runtime_profile": args.required_runtime_profile,
        "--required_runtime_profile_sha256": args.required_runtime_profile_sha256,
    }
    supplied = sorted(flag for flag, value in declared.items() if value is not None)
    if not supplied:
        return None
    if len(supplied) != len(declared):
        missing = sorted(flag for flag, value in declared.items() if value is None)
        raise SystemExit(
            f"an incomplete required runtime-profile binding was declared: "
            f"{', '.join(supplied)} passed without {', '.join(missing)}. The "
            f"binding is the TRIPLE (artifact path, profile key, certified "
            f"sha256) — a partial declaration is refused, never treated as "
            f"undeclared, because that would leave the requirement silently "
            f"unenforced."
        )
    try:
        return RequiredProfileBinding(
            artifact_path=args.required_runtime_profile_path,
            profile_key=args.required_runtime_profile,
            expected_sha256=args.required_runtime_profile_sha256,
        )
    except ValidationError as exc:
        raise SystemExit(
            f"invalid required runtime-profile declaration "
            f"(--required_runtime_profile_path="
            f"{args.required_runtime_profile_path!r}, "
            f"--required_runtime_profile={args.required_runtime_profile!r}, "
            f"--required_runtime_profile_sha256="
            f"{args.required_runtime_profile_sha256!r}): {exc}"
        ) from exc


def resolve_watchdog_policy(args: argparse.Namespace) -> ResolvedWatchdogSettings:
    """arXiv #261 / Q-07c-6 — resolve the launch's watchdog policy ONCE.

    Merges the operator's tri-state flags with the ``(device, regime)``
    runtime profile (``core.runtime_control.watchdog_profile`` is the sole
    authority; flags always win) and writes the FINAL values back onto
    ``args``, so the single ``WorkflowLaunchConfig`` construction site and
    the ``--print_resolved_launch_config`` view both read resolved truth.

    Idempotent by construction: the resolved settings are cached on
    ``args.runtime_watchdog_policy`` and returned verbatim on a second
    call, so provenance can never degrade to "cli" after the write-back
    turns the tri-state flag into a concrete bool.
    """
    cached = getattr(args, "runtime_watchdog_policy", None)
    if cached is not None:
        return cached
    required_binding = build_required_profile_binding(args)
    try:
        resolved = resolve_watchdog_launch_settings(
            cli_enabled=args.runtime_watchdog,
            cli_safety_factor=args.runtime_watchdog_safety_factor,
            cli_floor_seconds=args.runtime_watchdog_floor_seconds,
            execution_regime=args.execution_regime,
            required_binding=required_binding,
        )
    except RequiredProfileBindingError as exc:
        # The declared requirement could not be certified. Refuse the launch
        # loudly, naming the flag that declared it — a REQUIRED binding never
        # falls back to the shipped or uncalibrated profile.
        raise SystemExit(f"--required_runtime_profile: {exc}") from exc
    try:
        validate_phase_deadline(
            args.validation_max_phase_seconds, watchdog_enabled=resolved.enabled
        )
    except ValueError as exc:
        raise SystemExit(f"workflow launch refused before agent calls: {exc}") from exc
    args.runtime_watchdog = resolved.enabled
    args.runtime_watchdog_safety_factor = resolved.safety_factor
    args.runtime_watchdog_floor_seconds = resolved.floor_seconds
    args.runtime_watchdog_policy = resolved
    return resolved
