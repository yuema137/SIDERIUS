"""Types a custom adaptor function receives; importable by author code.

``adapt(inputs, params, ctx)`` gets read-only, validated native models in
declared port order. The context exposes no path, workspace, environment,
clock, random seed or LLM (v1 admits deterministic adaptors only).
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CustomInputItem:
    """One input value; ``index`` is its declared position within the port."""

    index: int
    value: Any


AdaptorInputs = Mapping[str, tuple[CustomInputItem, ...]]


@dataclass(frozen=True)
class AdaptorContext:
    """The only effects available to adaptor code."""

    adaptor_id: str
    llm: None = None

    def log(self, message: str) -> None:
        """Diagnostic text on the child's stderr; never part of the output."""
        print(f"[adaptor:{self.adaptor_id}] {message}", file=sys.stderr)
