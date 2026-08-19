# execute_tools/health_checks/__init__.py
"""
Pluggable health-check skill system.

Public surface:
    * :func:`register` / :func:`get` / :func:`all_registered` — registry access
    * :class:`HealthCheckContext` / :class:`HealthCheckResult` /
      :class:`GateResult` / :class:`GateAction` — typed data model
    * :class:`HealthCheckSkill` — the Protocol every check implements
    * :func:`evaluate_gate` / :func:`get_gates_for_position` /
      :func:`resolve_action` / :func:`severity_of` — runner API

Migration completed in commit-6: the rev-3 ``run_health_checks``
function (removed in commit-3a), the ``HealthCheckOutput`` /
``HealthCheckPanelOutput`` schemas, and the ``HealthCheckConfig`` /
``CheckConfig`` configs are all gone. All references now point at the
rev-6 HealthGate API.

Registration policy: import-time side effect. Concrete checks import at the
bottom of this file and self-register via :func:`register`. Adding a new
check = write the check file + append two lines here. See
``docs/design/pluggable_health_checks.md`` §4.

Tests that need registry isolation call ``_REGISTRY.clear()`` via a pytest
fixture and re-register the checks they exercise.
"""

from __future__ import annotations

from execute_tools.health_checks.amplitude_collapse import AmplitudeCollapseCheck
from execute_tools.health_checks.candidate_eligibility import (
    CandidateHealthValidity,
    classify_candidate_health,
    is_valid_candidate,
    required_blocking_gate_ids,
)
from execute_tools.health_checks.evaluation import evaluate_and_persist_health_gates
from execute_tools.health_checks.output_diversity import OutputDiversityCheck
from execute_tools.health_checks.output_std import OutputStdCheck
from execute_tools.health_checks.pearson_dispersion import PearsonDispersionCheck
from execute_tools.health_checks.per_file_output_std import PerFileOutputStdCheck
from execute_tools.health_checks.protocol import HealthCheckSkill
from execute_tools.health_checks.registry import (
    _REGISTRY,
    all_registered,
    get,
    register,
)
from execute_tools.health_checks.runner import (
    evaluate_gate,
    get_gates_for_position,
    resolve_action,
    severity_of,
)
from execute_tools.health_checks.sample_dispersion_floor import (
    SampleDispersionFloorCheck,
)
from execute_tools.health_checks.schemas import (
    BLOCKING_ACTIONS,
    GateAction,
    GateResult,
    HealthCheckContext,
    HealthCheckResult,
)
from execute_tools.health_checks.spectral_peak_ratio import SpectralPeakRatioCheck


def _bootstrap_registry() -> None:
    """Register the built-in checks. Idempotent under re-import.

    Guards against re-registration during test-suite runs that repeatedly
    import this module: if a check is already registered under its name,
    we silently skip. Tests that want a clean slate use ``_REGISTRY.clear()``
    and then call this bootstrap explicitly.
    """
    for check in (
        OutputDiversityCheck(),
        AmplitudeCollapseCheck(),
        OutputStdCheck(),
        PearsonDispersionCheck(),
        SpectralPeakRatioCheck(),
        PerFileOutputStdCheck(),
        # Step 08a 8.4-C negative control. Registered like any other
        # built-in, referenced by NO production YAML — being registered is
        # not being configured, and the config baseline test proves it
        # never fires in production.
        SampleDispersionFloorCheck(),
    ):
        if check.name not in _REGISTRY:
            register(check)


_bootstrap_registry()


__all__ = [
    "BLOCKING_ACTIONS",
    "CandidateHealthValidity",
    "GateAction",
    "GateResult",
    "HealthCheckContext",
    "HealthCheckResult",
    "HealthCheckSkill",
    "all_registered",
    "classify_candidate_health",
    "evaluate_and_persist_health_gates",
    "evaluate_gate",
    "get",
    "get_gates_for_position",
    "is_valid_candidate",
    "register",
    "required_blocking_gate_ids",
    "resolve_action",
    "severity_of",
]
