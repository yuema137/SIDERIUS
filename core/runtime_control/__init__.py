"""
core/runtime_control — generic runtime-verification framework (RT2).

Design: docs/design/runtime_estimation_and_watchdog.md (rev 5). The
framework is task-agnostic: phase identifiers, the Prediction /
Measurement / Actual data model, the component-first observation
schema, steady-state detection, and the `RuntimePhaseVerifier`
lifecycle. Task-specific workload RESOLUTION lives colocated with the
production engines (`execute_tools/workload_resolvers.py`).
"""

from core.runtime_control.adaptive import (
    AdaptiveUnitVerification,
    AdaptiveVerificationConfig,
)
from core.runtime_control.phases import RUNTIME_PHASES, RuntimePhase
from core.runtime_control.provenance import (
    capture_environment_provenance,
    capture_storage_provenance,
    classify_cache_state,
)
from core.runtime_control.records import (
    MEASUREMENT_BACKED_SOURCES,
    RUNTIME_VERIFICATION_RECORD_KEY,
    AdmissionRecord,
    Confidence,
    PhaseComponentRecord,
    PhaseMeasurement,
    PredictionError,
    PredictionSource,
    PriorAgreement,
    RuntimeObservation,
    RuntimePrediction,
    TotalRecord,
    VerificationResult,
    extract_runtime_observation,
    observation_totals_from_components,
    record_is_formal_verified,
)
from core.runtime_control.session import (
    ADMISSION_STAGE_POST_SETUP,
    RuntimeControlPolicy,
    RuntimeVerificationSession,
)
from core.runtime_control.steady_state import (
    SteadyStateConfig,
    SteadyStateDetection,
    SteadyStateDetector,
    detect_steady_state,
)
from core.runtime_control.verifier import RuntimePhaseVerifier
from core.runtime_control.workload import ResolvedPhaseWorkload

__all__ = [
    "ADMISSION_STAGE_POST_SETUP",
    "MEASUREMENT_BACKED_SOURCES",
    "RUNTIME_PHASES",
    "RUNTIME_VERIFICATION_RECORD_KEY",
    "AdaptiveUnitVerification",
    "AdaptiveVerificationConfig",
    "AdmissionRecord",
    "Confidence",
    "PhaseComponentRecord",
    "PhaseMeasurement",
    "PredictionError",
    "PredictionSource",
    "PriorAgreement",
    "ResolvedPhaseWorkload",
    "RuntimeControlPolicy",
    "RuntimeObservation",
    "RuntimePhase",
    "RuntimePhaseVerifier",
    "RuntimePrediction",
    "RuntimeVerificationSession",
    "SteadyStateConfig",
    "SteadyStateDetection",
    "SteadyStateDetector",
    "TotalRecord",
    "VerificationResult",
    "capture_environment_provenance",
    "capture_storage_provenance",
    "classify_cache_state",
    "detect_steady_state",
    "extract_runtime_observation",
    "observation_totals_from_components",
    "record_is_formal_verified",
]
