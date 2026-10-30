"""Safe error categories shared by console and composition-child Task summaries."""


def summary_error_message(error: Exception) -> str:
    """Use fixed categories: exception text and task-defined class names may contain secrets."""
    if isinstance(error, OSError):
        return "Filesystem error while reading task summary facts."
    if isinstance(error, (ValueError, TypeError)):
        return "Invalid value while reading task summary facts."
    return "Unexpected error while reading task summary facts."
