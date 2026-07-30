"""Stable behavioral identities for runtime-control components (C4).

Operator-approved scheme (runtime_estimation_and_calibration.md §23-C4
approval): ``<component-name>@<semver>+<config-sha256-12>``.

* The semantic version represents interface/schema compatibility and is
  bumped by hand with the interface.
* The config hash covers EXACTLY the behaviorally relevant policy
  configuration, built as a canonical structured payload — never
  ``repr()``, source bytes, unordered mappings, paths, hostnames,
  timestamps, hardware identity, or calibration contents. Those
  belong to separately recorded identities (hardware_profile_id,
  calibration_registry_id, …) in later run invariants.

Canonical serialization: JSON with sorted keys, explicit separators,
``ensure_ascii=False`` UTF-8 encoding → SHA-256 → first 12 lowercase
hex characters. Deterministic across processes, insertion orders, and
equivalent object constructions (mappings are sorted recursively; lists
are preserved in their DECLARED order because order is behaviorally
meaningful for precedence sequences).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _canonicalize(value: Any) -> Any:
    """Recursively normalize a payload: mappings → sorted-key dicts,
    tuples → lists, sets are REJECTED (no deterministic order of their
    own — callers must sort explicitly and thereby document the
    ordering's meaning)."""
    if isinstance(value, dict):
        return {str(k): _canonicalize(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(v) for v in value]
    if isinstance(value, (set, frozenset)):
        raise TypeError(
            "sets have no deterministic order — sort explicitly before hashing "
            "so the ordering's behavioral meaning is visible in the payload"
        )
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"non-canonical payload value of type {type(value).__name__}: {value!r}")


def config_hash12(payload: dict[str, Any]) -> str:
    """SHA-256 (first 12 lowercase hex) of the canonical JSON payload."""
    canonical = _canonicalize(payload)
    encoded = json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:12]


def component_identity(name: str, semver: str, payload: dict[str, Any]) -> str:
    """``<name>@<semver>+<config-sha256-12>`` per the approved scheme."""
    if not name or "@" in name or "+" in name:
        raise ValueError(f"invalid component name: {name!r}")
    parts = semver.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError(f"invalid semantic version: {semver!r}")
    return f"{name}@{semver}+{config_hash12(payload)}"
