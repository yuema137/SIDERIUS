"""One parser for the native chain's bounded, persisted token identity."""

import hashlib
import re


def parse_token_identity(raw: bytes, run_name: str) -> tuple[str, str]:
    """Return the format-checked identity and the digest of its original bytes."""
    if len(raw) > 256:
        raise ValueError("native token identity exceeds its bound")
    token = raw.decode().strip()
    if not re.fullmatch(re.escape(run_name) + r"-\d{8}T\d{6}-[1-9]\d*", token):
        raise ValueError("invalid native token id")
    return token, hashlib.sha256(raw).hexdigest()
