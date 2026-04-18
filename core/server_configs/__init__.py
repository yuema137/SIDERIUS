"""
core/server_configs/

Per-server calibration registry. Each file ``{hostname}.py`` exports a
module-level ``CONFIG: ServerConfig``. Use ``get_server_config`` to
resolve the right config for the current host; unknown hosts fall back
to ``ligroup`` with a one-time warning.

Deviates from docs/resource_estimator_implement.md §10.6 — rather than
a flat baseline × ``server_cpu_factor`` split, each server owns its
full measured constant. ``per_psd_segment_seconds`` is itself
server-dependent (CPU model differences change FFT cost), so the
baseline × factor split was a weaker abstraction than per-server
measurement. Deviation recorded in the K.2.5 commit-7 doc tick-off.
"""

from __future__ import annotations

import importlib
import socket
import warnings
from typing import Optional

from core.server_configs._base import ServerConfig


# Track hosts we've already warned about so each unknown host warns
# at most once per Python process (mirrors Phase F's unknown-GPU
# pattern). Tests monkeypatch this back to empty.
_WARNED_HOSTS: set[str] = set()


def get_server_config(hostname: Optional[str] = None) -> ServerConfig:
    """Return the ``ServerConfig`` for a hostname.

    Resolution:
      1. ``hostname is None`` → ``socket.gethostname()``.
      2. Try ``core.server_configs.{hostname}``; return its ``CONFIG``.
      3. On ``ModuleNotFoundError``, warn once for that host and
         return the ``ligroup`` config as the safe fallback.

    Args:
        hostname: Override for the current machine's hostname. Tests
            and the time-aggregator pass this explicitly; production
            callers usually omit it.

    Returns:
        The ``ServerConfig`` for that host, or the ``ligroup`` fallback.
    """
    if hostname is None:
        hostname = socket.gethostname()

    try:
        mod = importlib.import_module(f"core.server_configs.{hostname}")
    except ModuleNotFoundError:
        if hostname not in _WARNED_HOSTS:
            _WARNED_HOSTS.add(hostname)
            warnings.warn(
                f"No server config for hostname {hostname!r}; falling "
                f"back to ligroup defaults. Add "
                f"core/server_configs/{hostname}.py with measured "
                f"constants to remove this warning.",
                UserWarning,
                stacklevel=2,
            )
        from core.server_configs import ligroup
        return ligroup.CONFIG

    return mod.CONFIG


__all__ = ["ServerConfig", "get_server_config"]
