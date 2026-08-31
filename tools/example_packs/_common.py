"""Shared helpers for the PR0 example-pack tooling (I/O and integrity pins).

Nothing here interprets a task rule. The helpers know how to find the
checkout root, write JSON with one stable formatting, and compute / record
SHA-256 pins — the mechanics every pack writer needs and nothing more.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


def repo_root() -> Path:
    """The checkout root, derived from this file's location (CLAUDE.md portability).

    ``tools/example_packs/_common.py`` → ``parents[2]`` is the repository.
    Never the ambient working directory: the tooling and the tests must read
    the checkout they live in, not whichever clone the shell happens to be in.
    """
    return Path(__file__).resolve().parents[2]


def examples_root(root: Path | None = None) -> Path:
    return (root or repo_root()) / "examples"


def dump_json_text(payload: Any) -> str:
    """One stable JSON rendering for every tracked artifact.

    Sorted keys, two-space indent, trailing newline. Equality tests compare
    ``json.loads`` results, so the formatting is not load-bearing for
    correctness — it is load-bearing for reviewable diffs.
    """
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_text(path: Path, text: str) -> Path:
    """Write ``text`` at ``path`` (parents created), UTF-8, LF, and return the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def write_json(path: Path, payload: Any) -> Path:
    return write_text(path, dump_json_text(payload))


def sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_of_file(path: Path) -> str:
    return sha256_of_bytes(path.read_bytes())


def render_sha256sums(pins: Mapping[str, str]) -> str:
    """The ``sha256sum``-compatible text: ``<hex>  <name>`` per line, sorted by name."""
    return "".join(f"{pins[name]}  {name}\n" for name in sorted(pins))


def parse_sha256sums(text: str) -> dict[str, str]:
    """Inverse of :func:`render_sha256sums`; tolerant of blank lines only."""
    pins: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        digest, _, name = line.partition("  ")
        if len(digest) != 64 or not name:
            raise ValueError(f"malformed SHA256SUMS line: {raw!r}")
        pins[name] = digest
    return pins


def write_sha256sums(directory: Path, names: Iterable[str]) -> dict[str, str]:
    """Pin the named files under ``directory`` into ``directory/SHA256SUMS``.

    The pin is an INTEGRITY / PROVENANCE pin (design §3.2): it names the exact
    bytes reviewed and detects corruption; it does not by itself prove
    immutability (a file and its pin can change together — the frozen
    derivation rule + official provenance + review carry identity).
    """
    pins = {name: sha256_of_file(directory / name) for name in names}
    write_text(directory / "SHA256SUMS", render_sha256sums(pins))
    return pins
