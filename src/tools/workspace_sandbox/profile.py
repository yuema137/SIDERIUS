"""Explicit filesystem, network and environment declarations for one caller."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.layout import checkout_root, package_root

# These are Linux runtime locations, not scientific or hardware policy.
SYSTEM_DIRECTORIES = tuple(Path(p) for p in ("/usr", "/bin", "/sbin", "/lib", "/lib64"))
SYSTEM_FILES = tuple(Path(p) for p in ("/etc/ld.so.cache", "/etc/localtime"))
NETWORK_FILES = tuple(
    Path(p) for p in ("/etc/resolv.conf", "/etc/hosts", "/etc/nsswitch.conf", "/etc/ssl/certs")
)
_RESERVED_ENV = {
    "HOME",
    "PATH",
    "TMPDIR",
    "XDG_CACHE_HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "LANG",
    "LC_ALL",
    "BASH_ENV",
    "ENV",
    "GCONV_PATH",
    "LOCPATH",
}


def runtime_roots() -> tuple[Path, ...]:
    """The exact active environment, base Python and editable/package source."""
    return tuple(
        sorted(
            {
                Path(sys.prefix).resolve(),
                Path(sys.base_prefix).resolve(),
                # venv may target UV's version alias, distinct from base_prefix.
                Path(getattr(sys, "_base_executable", None) or sys.executable).parent.parent,
                (checkout_root() or package_root()).resolve(),
            }
        )
    )


def _canonical_path(path: Path) -> Path:
    if not path.is_absolute() or path != path.resolve():
        raise ValueError("use a canonical absolute path without symlink aliases or '..'")
    if not path.exists():
        raise ValueError(f"declared path does not exist: {path}")
    return path


class SandboxProfile(BaseModel):
    """No credentials, scientific defaults or shell fragments are stored here."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    workspace: Path
    read_only: tuple[Path, ...] = ()
    network: bool
    devices: tuple[Path, ...] = ()
    environment_names: tuple[str, ...] = ()
    timeout_seconds: float = Field(gt=0, allow_inf_nan=False)

    @field_validator("workspace")
    @classmethod
    def workspace_directory(cls, path: Path) -> Path:
        path = _canonical_path(path)
        if not path.is_dir():
            raise ValueError("workspace must be an existing directory")
        return path

    @field_validator("read_only")
    @classmethod
    def read_only_paths(cls, paths: tuple[Path, ...]) -> tuple[Path, ...]:
        for path in paths:
            _canonical_path(path)
            if not (path.is_dir() or path.is_file()):
                raise ValueError("read-only inputs must be regular files or directories")
        return paths

    @field_validator("devices")
    @classmethod
    def device_paths(cls, paths: tuple[Path, ...]) -> tuple[Path, ...]:
        for path in paths:
            _canonical_path(path)
            if not path.is_relative_to("/dev") or not path.is_char_device():
                raise ValueError("devices must be explicit character-device paths under /dev")
        return paths

    @field_validator("environment_names")
    @classmethod
    def environment_keys(cls, names: tuple[str, ...]) -> tuple[str, ...]:
        for name in names:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise ValueError("environment_names must contain variable names only")
            if name in _RESERVED_ENV or name.startswith(("LD_", "PYTHON")):
                raise ValueError(f"environment variable is reserved by the sandbox: {name}")
        if len(set(names)) != len(names):
            raise ValueError("environment_names contains duplicates")
        return names

    @model_validator(mode="after")
    def mount_boundaries(self) -> SandboxProfile:
        control_roots = tuple(Path(p) for p in ("/proc", "/dev", "/sandbox-home"))
        for path in (self.workspace, *self.read_only):
            if path in (Path("/"), Path("/tmp"), Path("/etc"), Path("/home")):
                raise ValueError(f"declare a specific project/resource path, not {path}")
            if any(path.is_relative_to(root) for root in control_roots):
                raise ValueError(f"path conflicts with sandbox control mounts: {path}")
        if self.workspace.is_relative_to("/sys"):
            raise ValueError("workspace cannot overlap read-only hardware metadata")
        for root in (*runtime_roots(), *SYSTEM_DIRECTORIES, Path("/etc")):
            if self.workspace.is_relative_to(root) or root.is_relative_to(self.workspace):
                raise ValueError(f"workspace overlaps the protected runtime: {root}")
        for path in self.read_only:
            if self.workspace.is_relative_to(path):
                raise ValueError("workspace cannot be inside or equal to a read-only root")
        return self
