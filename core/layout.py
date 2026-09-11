"""Locations owned by the installed distribution and its optional checkout.

An installation is not a repository. Only the exact source layout declared by
the adjacent SIDERIUS pyproject qualifies as a checkout; CWD and unrelated
ancestor repositories never participate in resolution.
"""

import tomllib
from pathlib import Path


def package_root() -> Path:
    """Directory containing the eight installed import packages."""
    return Path(__file__).resolve().parent.parent


def _checkout_for(source: Path) -> Path | None:
    source = source.resolve()
    packages = source.parent.parent
    candidate = packages.parent if packages.name == "src" else packages
    if not (candidate / ".git").exists():
        return None
    manifest = candidate / "pyproject.toml"
    try:
        config = tomllib.loads(manifest.read_text(encoding="utf-8"))
        discovery = config["tool"]["setuptools"]["packages"]["find"]
        expected = "src" if packages.name == "src" else "."
        if config["project"]["name"] != "siderius" or discovery["where"] != [expected]:
            return None
        if (candidate / expected / "core" / "layout.py").resolve() != source:
            return None
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return candidate


def checkout_root() -> Path | None:
    """Exact editable/source checkout, or None for an ordinary installation."""
    return _checkout_for(Path(__file__))


def require_checkout(root: str | Path | None) -> Path:
    """Refuse a checkout-only operation when no source checkout is available."""
    if root is None:
        raise FileNotFoundError(
            "This operation requires the SIDERIUS source checkout; "
            "supply an explicit external resource path for an installed package."
        )
    return Path(root)


def checkout_path(*parts: str) -> str | None:
    """Optional checkout resource location; existence is the reader's policy."""
    root = checkout_root()
    return str(root.joinpath(*parts)) if root is not None else None
