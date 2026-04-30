"""
Tests for core/server_configs/ dispatcher + ServerConfig schema.

K.2.5 Commit 4:
- get_server_config resolves known hostnames from their module.
- Unknown hostnames fall back to ligroup with a one-time warning.
- Default (hostname=None) reads socket.gethostname().
- ServerConfig is frozen and forbids extra fields.
"""

from __future__ import annotations

import warnings

import pytest

import core.server_configs as sc
from core.server_configs import ServerConfig, get_server_config


# ---------------------------------------------------------------------------
# get_server_config
# ---------------------------------------------------------------------------

class TestGetServerConfig:

    def test_ligroup_returns_measured_config(self):
        cfg = get_server_config("ligroup")
        assert isinstance(cfg, ServerConfig)
        assert cfg.hostname == "ligroup"
        # The exact measured value; if the constant is retuned this
        # assertion is intentionally noisy.
        # Recalibrated 2026-04-30 from V7 formal-round end-to-end timings
        # (was 0.613 from a single-file warm-cache micro-benchmark on 2026-04-18).
        assert cfg.per_psd_segment_seconds == pytest.approx(2.21)

    def test_unknown_host_falls_back_to_ligroup(self, monkeypatch):
        monkeypatch.setattr(sc, "_WARNED_HOSTS", set())
        with pytest.warns(UserWarning, match="No server config for hostname 'nonsense-host'"):
            cfg = get_server_config("nonsense-host")
        assert cfg.hostname == "ligroup"
        # Recalibrated 2026-04-30 from V7 formal-round end-to-end timings
        # (was 0.613 from a single-file warm-cache micro-benchmark on 2026-04-18).
        assert cfg.per_psd_segment_seconds == pytest.approx(2.21)

    def test_unknown_host_warns_only_once(self, monkeypatch):
        monkeypatch.setattr(sc, "_WARNED_HOSTS", set())
        with warnings.catch_warnings(record=True) as first:
            warnings.simplefilter("always")
            get_server_config("made-up-host")
        with warnings.catch_warnings(record=True) as second:
            warnings.simplefilter("always")
            get_server_config("made-up-host")
        assert len(first) == 1
        assert len(second) == 0

    def test_defaults_to_current_hostname(self, monkeypatch):
        """hostname=None → socket.gethostname() is consulted."""
        calls = []

        def _fake():
            calls.append(None)
            return "ligroup"

        monkeypatch.setattr(sc.socket, "gethostname", _fake)
        cfg = get_server_config()
        assert calls == [None]
        assert cfg.hostname == "ligroup"


# ---------------------------------------------------------------------------
# ServerConfig schema
# ---------------------------------------------------------------------------

class TestServerConfigSchema:

    def test_rejects_nonpositive_per_segment(self):
        with pytest.raises(Exception):
            ServerConfig(hostname="x", per_psd_segment_seconds=0.0)
        with pytest.raises(Exception):
            ServerConfig(hostname="x", per_psd_segment_seconds=-0.5)

    def test_rejects_empty_hostname(self):
        with pytest.raises(Exception):
            ServerConfig(hostname="", per_psd_segment_seconds=0.5)

    def test_rejects_extra_fields(self):
        """Typos in a server file should be a validation error, not
        silently ignored."""
        with pytest.raises(Exception):
            ServerConfig(
                hostname="x", per_psd_segment_seconds=0.5,
                per_segment_seconds=0.5,  # wrong field name
            )

    def test_frozen(self):
        cfg = ServerConfig(hostname="x", per_psd_segment_seconds=0.5)
        with pytest.raises(Exception):
            cfg.hostname = "y"
