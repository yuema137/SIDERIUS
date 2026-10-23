"""Offline native candidate preparation shared by Python and JSON callers."""

from .launch import prepare_candidate
from .models import CandidatePreparationReceipt, CandidatePreparationRequest
from .resolution import (
    ResolvedExternalLocation,
    ResolvedReusableCandidate,
    ReusableCandidateLocations,
    resolve_reusable_candidate,
)

__all__ = [
    "CandidatePreparationReceipt",
    "CandidatePreparationRequest",
    "ResolvedExternalLocation",
    "ResolvedReusableCandidate",
    "ReusableCandidateLocations",
    "prepare_candidate",
    "resolve_reusable_candidate",
]

from .reusable_admission import preflight_reusable_candidate
from .reusable_launch import prepare_reusable_candidate
from .reusable_models import (
    ReusableBindingCapture,
    ReusableBindingInspection,
    ReusableCandidatePreparationRequest,
    ReusablePreparationPlan,
    ReusablePreparationReceipt,
    ReusablePreparedSelection,
    VerifiedReusablePreparation,
)
from .reusable_selection import (
    inspect_current_reusable_binding,
    inspect_reusable_binding,
    select_reusable_preparation,
    verify_reusable_preparation,
)

__all__ += [
    "ReusableBindingCapture",
    "ReusableBindingInspection",
    "ReusableCandidatePreparationRequest",
    "ReusablePreparationPlan",
    "ReusablePreparationReceipt",
    "ReusablePreparedSelection",
    "VerifiedReusablePreparation",
    "inspect_current_reusable_binding",
    "inspect_reusable_binding",
    "preflight_reusable_candidate",
    "prepare_reusable_candidate",
    "select_reusable_preparation",
    "verify_reusable_preparation",
]
