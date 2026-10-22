"""One component rule for live generated model/loss filesystem consumers."""

from __future__ import annotations

import unicodedata


def validate_generated_artifact_name(value: object, *, field: str) -> str:
    """Return an unchanged component or refuse it before name-derived effects.

    Reject separators, dot components, colons (drive/stream syntax), and Unicode
    control characters. This is neither a sanitizer nor a universal filename
    portability or symlink-confinement guarantee. Archived records stay readable;
    live consumers decide which fields need this check.
    """
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or any(char in value for char in "/\\:")
        or any(unicodedata.category(char) == "Cc" for char in value)
    ):
        raise ValueError(
            f"{field} must be a non-empty filesystem component without dot components, "
            f"path separators, colons or control characters; got {value!r}"
        )
    return value
