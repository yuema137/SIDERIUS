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

Registration policy: import-time side effect. The BUILT-IN checks import at
the bottom of this file and self-register via :func:`register`.

**That import list is the built-ins' convenience bootstrap, not the
extension path** (Step 08b C2). An external task registers its own checks by
naming plugin files in its task health config; the run loads them through
:func:`load_task_health_plugins`, and they call the SAME public
:func:`register` the built-ins use. Adding a check therefore does NOT require
editing this file — a census test asserts it. See
``docs/design/pluggable_health_checks.md`` §4 and the Step-08b child design
§3.5.

Tests that need registry isolation call ``_REGISTRY.clear()`` via a pytest
fixture and re-register the checks they exercise.
"""

from __future__ import annotations

from execute_tools.health_checks._plugin_binding import (
    HealthBindingError,
    HealthPluginError,
    HealthPluginRunScopeError,
    ResolvedHealthPlugin,
    bound_view_capabilities,
    externally_registered_checks,
    externally_registered_view_providers,
    load_task_health_plugins,
    loaded_plugin_set,
    resolve_task_health_bindings,
)
from execute_tools.health_checks._view_provider import (
    HealthView,
    HealthViewMaterializationError,
    HealthViewProvider,
)
from execute_tools.health_checks.amplitude_collapse import AmplitudeCollapseCheck
from execute_tools.health_checks.candidate_eligibility import (
    CandidateHealthValidity,
    classify_candidate_health,
    is_valid_candidate,
)
from execute_tools.health_checks.categorical_distinct_symbols import (
    CategoricalDistinctSymbolsCheck,
)
from execute_tools.health_checks.categorical_dominant_fraction import (
    CategoricalDominantFractionCheck,
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
    all_registered_view_providers,
    get,
    get_view_provider,
    register,
    register_view_provider,
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
from execute_tools.health_checks.standard_views import (
    CATEGORICAL_PREDICTIONS,
    CONTINUOUS_SAMPLES,
    CategoricalPredictionsPayload,
    ContinuousSamplesPayload,
)


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
        # Step 08a 8.4-C negative control, upgraded at 08c into the generic
        # continuous-family check. Registered like any other built-in,
        # referenced by NO production YAML — being registered is not being
        # configured, and the config baseline test proves it never fires in
        # production.
        SampleDispersionFloorCheck(),
        # Step 08c generic categorical collapse family. Framework-shipped
        # built-ins joining the bootstrap is legal (§4.6): EXTERNAL checks
        # register through task plugins and never appear here. Like the
        # dispersion check, configured by NO shipped YAML — the consuming
        # tasks (Pets) bind them through their own pack configs.
        CategoricalDistinctSymbolsCheck(),
        CategoricalDominantFractionCheck(),
    ):
        if check.name not in _REGISTRY:
            register(check)


_bootstrap_registry()


__all__ = [
    "BLOCKING_ACTIONS",
    "CATEGORICAL_PREDICTIONS",
    "CONTINUOUS_SAMPLES",
    "CandidateHealthValidity",
    "CategoricalPredictionsPayload",
    "ContinuousSamplesPayload",
    "GateAction",
    "GateResult",
    "HealthBindingError",
    "HealthCheckContext",
    "HealthCheckResult",
    "HealthCheckSkill",
    "HealthPluginError",
    "HealthPluginRunScopeError",
    "HealthView",
    "HealthViewMaterializationError",
    "HealthViewProvider",
    "ResolvedHealthPlugin",
    "all_registered",
    "all_registered_view_providers",
    "bound_view_capabilities",
    "classify_candidate_health",
    "evaluate_and_persist_health_gates",
    "evaluate_gate",
    "externally_registered_checks",
    "externally_registered_view_providers",
    "get",
    "get_gates_for_position",
    "get_view_provider",
    "is_valid_candidate",
    "load_task_health_plugins",
    "loaded_plugin_set",
    "register",
    "register_view_provider",
    "resolve_action",
    "resolve_task_health_bindings",
    "severity_of",
]
