"""Safe console diagnostics; classification belongs to setup_review.summary_errors."""

import logging

from tools.setup_review.summary_errors import error_category

logger = logging.getLogger(__name__)


def console_error_message(error: Exception) -> str:
    """Keep the cause in server diagnostics, returning only fixed category text."""
    logger.error("Console operation failed", exc_info=(type(error), error, error.__traceback__))
    return {
        "filesystem": "Filesystem error. See the diagnostic log for details.",
        "invalid": "Invalid value. See the diagnostic log for details.",
        "unexpected": "Unexpected error. See the diagnostic log for details.",
    }[error_category(error)]
