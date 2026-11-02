"""Safe error categories shared by task summaries and preparation status."""

import builtins
from json import JSONDecodeError
from typing import Literal


def error_category(error: Exception | str) -> Literal["filesystem", "invalid", "unexpected"]:
    """Classify exceptions or legacy receipt diagnostics without echoing their contents.

    Serialized custom exception names have no trustworthy hierarchy. Recognize only
    standard exception classes; never import or instantiate a task-defined class.
    """
    if isinstance(error, str):
        name = error.partition(":")[0]
        error_type = {"JSONDecodeError": JSONDecodeError, "ValidationError": ValueError}.get(name)
        if error_type is None:
            error_type = getattr(builtins, name, None)
        if not isinstance(error_type, type) or not issubclass(error_type, Exception):
            return "unexpected"
    else:
        error_type = type(error)
    if issubclass(error_type, OSError):
        return "filesystem"
    if issubclass(error_type, (ValueError, TypeError)):
        return "invalid"
    return "unexpected"


def summary_error_message(error: Exception | str) -> str:
    """Use fixed categories: exception text and task-defined class names may contain secrets."""
    return {
        "filesystem": "Filesystem error while reading task summary facts.",
        "invalid": "Invalid value while reading task summary facts.",
        "unexpected": "Unexpected error while reading task summary facts.",
    }[error_category(error)]
