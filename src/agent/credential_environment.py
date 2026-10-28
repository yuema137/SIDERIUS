"""Observable compatibility dotenv loading and blank-credential warnings.

This module is the single owner of two diagnostics for command-line credential
loading. It never changes which file is loaded, never overrides an existing
variable and never refuses; it only logs. Messages carry file paths, modes and
variable names, never variable values.

- ``load_compatibility_dotenv`` wraps python-dotenv with its default search
  and ``override=False``. Called with no path, ``find_dotenv()`` starts from
  this module's directory (``src/agent``), the same directory the bridge's
  former bare ``load_dotenv()`` used, so the same file is chosen. When a file
  actually loads, the resolved path is logged once per process at INFO, with
  a WARNING if the file lies outside the SIDERIUS source checkout (or no
  checkout exists) or if its mode grants any group/other permission.
- ``warn_if_blank_credential`` warns by name when a required key variable is
  present but empty or whitespace-only.
"""

from __future__ import annotations

import logging
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from core.layout import checkout_root

logger = logging.getLogger(__name__)

#: Resolved dotenv paths already reported in this process.
_REPORTED_DOTENV_PATHS: set[Path] = set()


def load_compatibility_dotenv(dotenv_path: str | Path | None = None) -> bool:
    """Load a compatibility dotenv file exactly as python-dotenv would, then report it.

    Args:
        dotenv_path: explicit file to load, or ``None`` for python-dotenv's
            default upward search (``find_dotenv()``).

    Returns:
        python-dotenv's result: True when a non-empty file was read, even if every
        variable in it was already set (that case is still reported).
    """
    path = str(dotenv_path) if dotenv_path is not None else find_dotenv()
    if not path:
        return False
    loaded = load_dotenv(dotenv_path=path)
    if loaded:
        _report_dotenv_provenance(Path(path).resolve())
    return loaded


def _report_dotenv_provenance(resolved: Path) -> None:
    """Log the loaded file's path once per process and warn about its location or mode."""
    if resolved in _REPORTED_DOTENV_PATHS:
        return
    _REPORTED_DOTENV_PATHS.add(resolved)
    logger.info(
        "Compatibility dotenv loaded %s (variables already set in the environment take precedence).",
        resolved,
    )
    root = checkout_root()
    if root is None:
        logger.warning(
            "Compatibility dotenv file %s was loaded but no SIDERIUS source checkout was "
            "detected; it was found by searching parent directories. Bind credentials in "
            "the launching process instead.",
            resolved,
        )
    elif not resolved.is_relative_to(root.resolve()):
        logger.warning(
            "Compatibility dotenv file %s is outside the SIDERIUS checkout %s; it was found "
            "by searching parent directories. Bind credentials in the launching process or "
            "move the file into this checkout.",
            resolved,
            root.resolve(),
        )
    try:
        mode = resolved.stat().st_mode & 0o777
    except OSError:
        return
    if mode & 0o077:
        logger.warning(
            "Compatibility dotenv file %s is accessible to group or other users (mode %03o); "
            "restrict it with chmod 600.",
            resolved,
            mode,
        )


def warn_if_blank_credential(name: str, value: str | None, *, provider: str) -> None:
    """Warn by name when a required credential variable is set but empty or whitespace."""
    if value is not None and not value.strip():
        logger.warning(
            "%s is set but empty or whitespace-only; provider %r will receive no usable "
            "credential. Set a non-empty value or unset it.",
            name,
            provider,
        )
