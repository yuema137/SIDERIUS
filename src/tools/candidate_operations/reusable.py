"""Configured reusable selection policy and one preparation-owned provenance check."""

from uuid import UUID

from tools.candidate_prepare import (
    ReusablePreparedSelection,
    VerifiedReusablePreparation,
    verify_reusable_preparation,
)
from tools.candidate_worker.models import CandidateRunRequest

from .files import canonical, overlap
from .models import CandidateOperation, OperationFailure, OperationStoreConfig


def validate_selection_root(
    config: OperationStoreConfig, selection: ReusablePreparedSelection
) -> None:
    """Static containment only: recovery must not require surviving prepared files."""
    envelope = canonical(selection.envelope)
    if not any(
        envelope != canonical(root) and envelope.is_relative_to(canonical(root))
        for root in config.preparation_roots
    ):
        raise OperationFailure("path", "reusable envelope is outside configured preparation roots")
    if overlap(canonical(config.state_root), envelope):
        raise OperationFailure("path", "operation state overlaps reusable envelope")


def verify_reusable_operation(
    config: OperationStoreConfig, submission: CandidateOperation
) -> VerifiedReusablePreparation | None:
    """Fresh content check for a new admission or dispatch; never for existing-ID recovery.

    The operator's explicit ``run_seed`` is the one field a candidate may add to
    the prepared request: the preparation never chooses the candidate's seed.
    """
    selection = submission.reusable_preparation
    if selection is None:
        return None
    validate_selection_root(config, selection)
    try:
        verified = verify_reusable_preparation(selection)
        if verified.request != submission.request.model_copy(update={"run_seed": None}):
            raise ValueError("submitted request differs from selected preparation")
    except (OSError, ValueError) as error:
        raise OperationFailure(
            "reusable_preparation", "reusable preparation no longer matches the selected request"
        ) from error
    return verified


def build_reusable_operation(
    config: OperationStoreConfig,
    selection: ReusablePreparedSelection,
    request_id: UUID,
    run_seed: int | None = None,
) -> CandidateOperation:
    """Review a retained selection under store policy; submit rechecks it before claiming.

    ``run_seed`` is the operator's explicit candidate seed (issue #983), the one
    field a candidate may add to the prepared request; ``None`` leaves the
    prepared request, and its digest, unchanged.
    """
    # Keep store validation independent of this read boundary and its mutable files.
    from .store import validate_config, validate_submission

    config = validate_config(config)
    selection = ReusablePreparedSelection.model_validate_json(selection.model_dump_json())
    validate_selection_root(config, selection)
    try:
        verified = verify_reusable_preparation(selection)
    except (OSError, ValueError) as error:
        raise OperationFailure(
            "reusable_preparation", "reusable preparation no longer matches the retained selection"
        ) from error
    request = verified.request
    if run_seed is not None:
        # Revalidate so an out-of-range seed is refused here, not at admission.
        request = CandidateRunRequest.model_validate_json(
            request.model_copy(update={"run_seed": run_seed}).model_dump_json()
        )
    submission = CandidateOperation(
        request_id=request_id, request=request, reusable_preparation=selection
    )
    validate_submission(config, submission)
    return submission
