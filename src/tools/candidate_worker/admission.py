"""Shared native selected-input mount admission, without widening sandbox roots."""

from collections.abc import Iterable
from pathlib import Path

from tools.workspace_sandbox.profile import runtime_roots


def admit_input_paths(paths: Iterable[Path], read_only: tuple[str, ...]) -> None:
    roots = (*(Path(value).resolve() for value in read_only), *runtime_roots())
    for path in paths:
        if not any(path.is_relative_to(root) for root in roots):
            raise ValueError(f"selected input needs an explicit read-only mount: {path}")
