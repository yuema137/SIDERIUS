"""CLI-safe configuration diagnostics: schema locations/types, never input values."""

import json
import re
from typing import get_args

from pydantic import BaseModel, ValidationError
from pydantic_core import ErrorType

from .models import ConsoleConfig
from .settings_models import ConsoleFile


class MissingConfigFile(ValueError):
    """An explicitly identified operator resource is absent; safe for CLI display."""

    def __init__(self, item: str, field: str, path: str):
        # Keep even a path containing line breaks on one diagnostic line.
        display = json.dumps(path, ensure_ascii=True)[1:-1]
        super().__init__(f"{item}: {field} file {display} is missing")


def _vocabulary() -> set[str]:
    names: set[str] = set()
    visited: set[type[BaseModel]] = set()

    def visit(annotation: object) -> None:
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            if annotation in visited:
                return
            visited.add(annotation)
            for name, field in annotation.model_fields.items():
                names.add(name)
                visit(field.annotation)
        for argument in get_args(annotation):
            visit(argument)

    visit(ConsoleConfig)
    visit(ConsoleFile)
    return names


def _safe_extra_name(name: str) -> bool:
    """Conservatively distinguish short field identifiers from pasted token-like keys."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,31}", name):
        return False
    if name.lower().startswith(("ghp_", "sk-", "sk_")):
        return False
    # Long, mostly alphanumeric strings can be base64/URL-safe token material.
    # False positives hide a location segment; they never change validation.
    return not (len(name) >= 16 and sum(c.isalnum() for c in name) / len(name) >= 0.9)


def invalid_config_fields(error: ValidationError) -> tuple[str, ...]:
    """One diagnostic per error; arbitrary mapping keys/union labels stay redacted.

    Extra fields are locations too: show simple identifier-shaped names, but never
    arbitrary text (e.g. a pasted credential) as an unknown location segment.
    """
    names = _vocabulary()
    source = (
        "console.json"
        if error.title == ConsoleFile.__name__
        else "resolved console configuration (console.json, global settings, workspace layout)"
    )
    error_types = get_args(ErrorType)
    messages: list[str] = []
    for item in error.errors(include_input=False, include_context=False, include_url=False):
        location = ""
        parts = item["loc"]
        for index, part in enumerate(parts):
            if isinstance(part, int):
                location += f"[{part}]"
                continue
            elif item["type"] == "extra_forbidden" and index == len(parts) - 1:
                segment = part if _safe_extra_name(part) else "<key>"
            elif part in names:
                segment = part
            else:
                segment = "<key>"
            location += ("." if location else "") + segment
        kind = item["type"] if item["type"] in error_types else "validation_error"
        messages.append(f"{source} is invalid at {location or '(document)'} ({kind})")
    return tuple(messages)
