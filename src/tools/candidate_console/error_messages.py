"""Safe console diagnostics; classification belongs to setup_review.summary_errors."""

import logging

from tools.setup_review.composition_models import CompositionObservation
from tools.setup_review.summary_errors import error_category
from tools.workflow_authoring.models import ReviewView

logger = logging.getLogger(__name__)


def console_error_message(error: Exception) -> str:
    """Keep the cause in server diagnostics, returning only fixed category text."""
    logger.error("Console operation failed", exc_info=(type(error), error, error.__traceback__))
    return {
        "filesystem": "Filesystem error. See the diagnostic log for details.",
        "invalid": "Invalid value. See the diagnostic log for details.",
        "unexpected": "Unexpected error. See the diagnostic log for details.",
    }[error_category(error)]


def advice_error_message(error: Exception) -> str:
    """Retain actionable advice format guidance without quoting uploaded keys or causes."""
    from workflows.advice import ADVICE_RECOGNISED_KEYS

    return (
        console_error_message(error)
        + " Advice needs nonempty text or lists of text under recognised keys: "
        + ", ".join(ADVICE_RECOGNISED_KEYS)
        + "."
    )


def safe_observation(observation: CompositionObservation) -> CompositionObservation:
    """Copy a native observation for HTTP; retain private diagnostics in the server log."""
    from tools.setup_review.summary_errors import summary_error_message

    failure = observation.result.failure
    if failure is None:
        return observation
    logger.error(
        "Editor task inspection %s (%s): %s", failure.stage, failure.exception_type, failure.message
    )
    safe = failure.model_copy(
        update={
            "exception_type": error_category(failure.exception_type),
            "message": summary_error_message(failure.exception_type),
        }
    )
    return observation.model_copy(
        update={"result": observation.result.model_copy(update={"failure": safe})}
    )


def safe_review(review: ReviewView) -> ReviewView:
    """Project target and previous task observations without mutating the authoring result."""
    task = review.task_reference_update
    if task is None:
        return review
    safe = task.model_copy(
        update={
            "observation": safe_observation(task.observation),
            "current_observation": safe_observation(task.current_observation)
            if task.current_observation is not None
            else None,
        }
    )
    return review.model_copy(update={"task_reference_update": safe})
