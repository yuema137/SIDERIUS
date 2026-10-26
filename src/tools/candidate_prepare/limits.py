"""Shared per-file envelope for native preparation writes and bounded reads."""

PREPARATION_FILE_LIMIT = 16 * 1024 * 1024


def bounded_payload(payload: bytes) -> bytes:
    """Refuse bytes that the existing preparation reader cannot consume."""
    if len(payload) > PREPARATION_FILE_LIMIT:
        raise ValueError("native payload exceeds preparation read limit")
    return payload
