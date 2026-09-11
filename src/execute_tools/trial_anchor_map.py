"""Read a caller-provided trial anchor-map artifact.

Anchor maps are task-owned inputs.  This module deliberately only performs
explicit JSON loading and validates the established ``s_max``/``anchors``
payload boundary; construction and default-path policy belong to the task
consumer.
"""

from __future__ import annotations

import json
import os


def load_anchor_map(path: str) -> dict:
    """Load an explicit anchor-map JSON file without choosing a default path.

    Raises ``FileNotFoundError`` for a missing path and ``ValueError`` for
    malformed JSON or a JSON value lacking the required payload keys.  The
    decoded mapping is returned unchanged.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"segment anchor map not found at {path!r}. Prepare the caller- or "
            "task-owned anchor artifact and pass its explicit path."
        )
    try:
        with open(path, encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as error:
        raise ValueError(f"segment anchor map at {path!r} is malformed JSON: {error}") from error
    if not isinstance(data, dict) or "s_max" not in data or "anchors" not in data:
        found = sorted(data) if isinstance(data, dict) else type(data).__name__
        raise ValueError(
            f"segment anchor map at {path!r} is missing required keys "
            f"('s_max', 'anchors'); found {found}."
        )
    return data


__all__ = ["load_anchor_map"]
