"""Build a bubblewrap invocation; values are passed via env, never argv."""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from core.runtime_control.process_visibility import PROCESS_VISIBILITY_ENV
from tools.workspace_sandbox.profile import (
    NETWORK_FILES,
    SYSTEM_DIRECTORIES,
    SYSTEM_FILES,
    SandboxProfile,
    runtime_roots,
)


class SandboxUnavailable(RuntimeError):
    """The explicitly requested execution boundary cannot be established."""


def child_environment(profile: SandboxProfile, source: Mapping[str, str]) -> dict[str, str]:
    missing = [name for name in profile.environment_names if not source.get(name)]
    if missing:
        raise SandboxUnavailable("export required environment variable(s): " + ", ".join(missing))
    env = {name: source[name] for name in profile.environment_names}
    env.update(
        {
            "HOME": "/sandbox-home",
            PROCESS_VISIBILITY_ENV: "namespace_limited",
            # getpass users (including PyTorch cache setup) need an identity
            # without exposing the host's account database.
            "USER": "siderius",
            "LOGNAME": "siderius",
            "TMPDIR": "/tmp",
            "XDG_CACHE_HOME": "/sandbox-home/cache",
            "XDG_CONFIG_HOME": "/sandbox-home/config",
            "XDG_DATA_HOME": "/sandbox-home/data",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin",
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return env


def command_prefix(profile: SandboxProfile) -> list[str]:
    if sys.platform != "linux":
        raise SandboxUnavailable("workspace sandbox requires Linux with bubblewrap")
    executable = shutil.which("bwrap")
    if executable is None:
        raise SandboxUnavailable(
            "install bubblewrap (bwrap) and enable user namespaces on this host"
        )
    args = [executable, "--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL"]
    if profile.network:
        args.append("--share-net")
    args.extend(["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", "/sandbox-home"])
    for path in (*SYSTEM_DIRECTORIES, *SYSTEM_FILES, *(NETWORK_FILES if profile.network else ())):
        if path.exists():
            args.extend(["--ro-bind", str(path), str(path)])
    # Preserve original paths for pyvenv.cfg, editable .pth and UV Python symlinks.
    # System /bin and /lib symlinks are handled only in the known runtime list.
    for root in runtime_roots():
        args.extend(["--ro-bind", str(root), str(root)])
    args.extend(["--bind", str(profile.workspace), str(profile.workspace)])
    # Freeze declared task/config descendants after the writable project mount.
    for path in sorted(set(profile.read_only), key=lambda p: (len(p.parts), str(p))):
        args.extend(["--ro-bind", str(path), str(path)])
    for path in profile.devices:
        args.extend(["--dev-bind", str(path), str(path)])
    args.extend(["--remount-ro", "/", "--chdir", str(profile.workspace)])
    return args


def build_command(profile: SandboxProfile, argv: Sequence[str]) -> tuple[list[str], dict[str, str]]:
    if not argv or not argv[0] or any("\0" in value for value in argv):
        raise ValueError("supply a nonempty command after --, without NUL characters")
    # Revalidate at use time: parsed paths may have changed since the profile was read.
    profile = SandboxProfile.model_validate(profile.model_dump())
    env = child_environment(profile, os.environ)
    return [*command_prefix(profile), "--", *argv], env
