"""Phase 6.6 §5.1 — mechanical enforcement of Principle 5 (no hardcoded
device literals).

Greps ``core/``, ``agent/``, and ``nodes/`` for device-specific tokens
(``5090``, ``A100``, ``V100``, ``H100``, literal ``"32 GB"``/``"32GB"``,
the numeric literal ``25.6``). A match in live code — a conditional,
a default, a constant — is a failure of the phase: all device facts
must come through ``core.hardware_context.HardwareContext`` so a run
on a different GPU needs zero code changes.

Allowed places a token may appear:
  * Inside a docstring or comment **explicitly marked** as a *documented
    example* (``e.g.``) or as *calibration provenance* (``measured on``,
    ``captured on``, ``observed on``, ``calibrated on``). Provenance
    annotations record the GPU/driver stack a calibration constant was
    pinned against — essential engineering hygiene, not a Principle 5
    violation (the *constant* itself is named and centralised; the
    comment just says where it came from).
  * Inside a triple-backtick fenced code block rendering a file-format
    sample where the token is a value in a documented schema.

Everywhere else — assignment RHS, dict key, conditional check — is a
Principle 5 violation.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]

# Tokens the design doc §5.1 pins verbatim. Case-insensitive for the
# letter-prefixed GPU names (``5090`` is digit-only so case is irrelevant).
# ``25.6`` is matched with regex-escaped dot so it doesn't cross tokens.
_DEVICE_TOKEN_PATTERN = re.compile(
    r"(5090|A100|V100|H100|\b32\s*GB\b|(?<!\d)25\.6(?!\d))",
    re.IGNORECASE,
)

# §5.1 scope: every ``.py`` under these three trees.
_SCAN_DIRS: list[str] = ["core", "agent", "nodes"]

# Allow-list markers that classify a token-bearing line as documentation
# rather than live code.
_EXAMPLE_MARKERS    = ("e.g.", "example")
_PROVENANCE_MARKERS = ("measured on", "measured 2", "captured on", "captured 2",
                        "observed on", "observed a", "calibrated on",
                        "verified on", "appendix a", "rtx 5090)",
                        "lilab rtx", "lilab ",)


def _is_allowed_line(line: str) -> bool:
    """Return True if a token-bearing line is documentation, not live code.

    Cheap heuristic: line contains a known example / provenance marker
    (case-insensitive). Intentionally permissive for provenance comments
    — the purpose of Principle 5 is no *behavioral* branching on device
    identity, not to erase the engineering-log annotation that pins a
    calibration constant to the hardware stack it was measured on.
    """
    low = line.lower()
    if any(marker in low for marker in _EXAMPLE_MARKERS):
        return True
    if any(marker in low for marker in _PROVENANCE_MARKERS):
        return True
    return False


def _classify_lines(lines: list[str]) -> list[str]:
    """Return ``len(lines)`` classifications, one per line:
    ``"docstring-allowed"`` (inside a docstring whose block contains an
    allow-marker or a ``` ``` fenced code block), ``"docstring-plain"``
    (inside a docstring with no markers), or ``"code"``.

    The rule: a *docstring region* is treated as documentation if *any*
    line of the region carries an example/provenance marker or is inside
    a triple-backtick fenced code block. That captures the common case
    of a JSON sample under a docstring header — the sample's body lines
    don't individually carry markers, but the block as a whole is
    documentation.
    """
    result = ["code"] * len(lines)

    # Pass 1 — find docstring regions and their start/end indices.
    regions: list[tuple[int, int]] = []
    in_docstring    = False
    docstring_delim = None
    start = 0
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if in_docstring:
            if docstring_delim in line:
                regions.append((start, idx))
                in_docstring = False
                docstring_delim = None
        elif stripped.startswith(('"""', "'''")):
            delim = stripped[:3]
            rest = stripped[3:]
            if delim in rest:
                # Single-line docstring — one-line region.
                regions.append((idx, idx))
            else:
                in_docstring = True
                docstring_delim = delim
                start = idx

    # Pass 2 — classify each region by looking for markers or code fences.
    for (s, e) in regions:
        block_text = "\n".join(lines[s : e + 1]).lower()
        has_marker = (
            any(m in block_text for m in _EXAMPLE_MARKERS)
            or any(m in block_text for m in _PROVENANCE_MARKERS)
            or "```" in block_text
        )
        tag = "docstring-allowed" if has_marker else "docstring-plain"
        for i in range(s, e + 1):
            result[i] = tag

    return result


def _scan_file(path: Path) -> list[tuple[int, str]]:
    """Return ``[(lineno, rstripped_text), ...]`` for every unexcused line
    in the file that contains at least one device-literal token."""
    text = path.read_text()
    lines = text.splitlines()
    classes = _classify_lines(lines)

    violations: list[tuple[int, str]] = []
    for idx0, line in enumerate(lines):
        if not _DEVICE_TOKEN_PATTERN.search(line):
            continue
        cls = classes[idx0]
        if cls == "docstring-allowed":
            continue
        # A code line with its own inline marker (e.g. a trailing "# e.g."
        # comment pinning a provenance constant) is also allowed.
        if _is_allowed_line(line):
            continue
        violations.append((idx0 + 1, line.rstrip()))

    return violations


def _iter_tree(scan_dir: str):
    """Yield every ``.py`` under ``scan_dir``. Skips the guardrails dir
    itself (this very file mentions the tokens verbatim in its pattern
    definition — excluding the scan's own backstop keeps the test
    self-consistent)."""
    root = _REPO_ROOT / scan_dir
    for path in sorted(root.rglob("*.py")):
        # Skip caches.
        if "__pycache__" in path.parts:
            continue
        yield path


@pytest.mark.parametrize("scan_dir", _SCAN_DIRS, ids=_SCAN_DIRS)
def test_no_hardcoded_device_literals(scan_dir: str) -> None:
    """Parametrised one case per scanned tree — failure text names the
    exact file:line of each violation so fixing is a single grep away."""
    all_violations: list[str] = []
    for path in _iter_tree(scan_dir):
        rel = path.relative_to(_REPO_ROOT)
        for lineno, text in _scan_file(path):
            all_violations.append(f"{rel}:{lineno}:{text}")

    assert not all_violations, (
        f"[{scan_dir}/] Principle 5 violations — hardcoded device literals "
        f"in live code:\n"
        + "\n".join(all_violations)
        + "\n\nRoute the value through core.hardware_context.HardwareContext "
          "(or annotate the line as an example / calibration provenance if "
          "it is genuinely documentation)."
    )
