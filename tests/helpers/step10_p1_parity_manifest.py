"""Step 10 / P1 — reduce an LLM-facing capture to a committable manifest.

The capture produced by ``tests/helpers/step09_5a_llm_parity_capture.py`` is
several megabytes of prompt bytes: real evidence, but not something to commit
or to diff by eye. This module reduces one capture to a small canonical
manifest that still pins **all seven required parity dimensions** (P1 design
§10 item 5):

    call count      len(calls)
    call order      the ordered list itself
    labels          per-call ``label``
    methods         per-call ``method``
    system bytes    per-call length AND sha256 of the exact string
    user bytes      per-call length AND sha256 of the exact string
    structured      sha256 over the canonical JSON of the kwargs dict

A sha256 over the reduced manifest is the single number quoted in the ledger.
Hashing the bytes rather than storing them is what makes the evidence
committable without storing 5 MB of prompts — and a hash mismatch localizes
to a call index, a dimension and a label, which a single payload-wide digest
would not.

USAGE

    # capture both sides with the 09.5a harness (both in worktrees sharing
    # one agent_generated — see that module's docstring), then:
    python -m tests.helpers.step10_p1_parity_manifest <capture.json> <manifest.json>

and compare two manifests with :func:`diff_manifests`, which reports the first
differing call and dimension rather than "the hashes differ".
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def build_manifest(capture: dict[str, Any]) -> dict[str, Any]:
    """Reduce a raw capture payload to the canonical parity manifest."""
    calls = capture["captures"]
    rows: list[dict[str, Any]] = []
    for index, call in enumerate(calls):
        system = call.get("system")
        user = call.get("user")
        rows.append(
            {
                "index": index,
                "method": call.get("method"),
                "label": call.get("label"),
                "system_bytes": len(system) if isinstance(system, str) else None,
                "system_sha256": _sha(system) if isinstance(system, str) else None,
                "user_bytes": len(user) if isinstance(user, str) else None,
                "user_sha256": _sha(user) if isinstance(user, str) else None,
                "kwargs_sha256": _sha(_canonical(call.get("kwargs", {}))),
            }
        )
    manifest = {
        "call_count": len(calls),
        "terminated_with": capture.get("terminated_with"),
        "calls": rows,
    }
    manifest["manifest_sha256"] = _sha(_canonical(manifest))
    return manifest


DIMENSIONS = (
    "method",
    "label",
    "system_bytes",
    "system_sha256",
    "user_bytes",
    "user_sha256",
    "kwargs_sha256",
)


def diff_manifests(base: dict[str, Any], head: dict[str, Any]) -> list[str]:
    """Human-readable differences; empty list means exact parity."""
    problems: list[str] = []
    if base["call_count"] != head["call_count"]:
        problems.append(f"call count: base={base['call_count']} head={head['call_count']}")
    if base.get("terminated_with") != head.get("terminated_with"):
        problems.append(
            f"termination: base={base.get('terminated_with')!r} "
            f"head={head.get('terminated_with')!r}"
        )
    for base_row, head_row in zip(base["calls"], head["calls"], strict=False):
        for dimension in DIMENSIONS:
            if base_row.get(dimension) != head_row.get(dimension):
                problems.append(
                    f"call {base_row['index']} ({base_row.get('label')}): "
                    f"{dimension} base={base_row.get(dimension)!r} "
                    f"head={head_row.get(dimension)!r}"
                )
    return problems


def main(capture_path: str, manifest_path: str) -> None:
    capture = json.loads(Path(capture_path).read_text(encoding="utf-8"))
    manifest = build_manifest(capture)
    Path(manifest_path).write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    print(f"calls={manifest['call_count']} manifest_sha256={manifest['manifest_sha256']}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
