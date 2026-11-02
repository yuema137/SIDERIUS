"""Emit the marked startup record consumed by browser fixture_metadata.mjs."""

import json
from collections.abc import Mapping


def emit_metadata(metadata: Mapping[str, object]) -> None:
    """Flush one metadata record, independently of unrelated startup stdout."""
    print("SIDERIUS_BROWSER_METADATA " + json.dumps(dict(metadata)), flush=True)
