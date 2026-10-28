"""Compatibility dotenv provenance (audit R5) and blank-credential warnings (R9).

Every file and value here is fake and lives under ``tmp_path``; the default
upward search is never exercised, so no real ``.env`` can be read.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import pytest

from agent import credential_environment, llm_bridge
from agent.credential_environment import load_compatibility_dotenv
from agent.llm_bridge import _KNOWN_PROVIDERS, _provider_credential_or_refuse

FAKE_NAME = "SIDERIUS_FAKE_DOTENV_PROBE"
FAKE_VALUE = "fake-secret-value-0123456789"
LOGGER = credential_environment.__name__


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, caplog):
    monkeypatch.setattr(credential_environment, "_REPORTED_DOTENV_PATHS", set())
    monkeypatch.delenv("PYTHON_DOTENV_DISABLED", raising=False)
    # setenv then delenv so monkeypatch restores the variable the loader adds.
    monkeypatch.setenv(FAKE_NAME, "placeholder")
    monkeypatch.delenv(FAKE_NAME)
    caplog.set_level(logging.INFO, logger=LOGGER)


def _dotenv(directory, mode):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ".env"
    path.write_text(f"{FAKE_NAME}={FAKE_VALUE}\n", encoding="utf-8")
    path.chmod(mode)
    return path


def _records(caplog, level):
    return [r.getMessage() for r in caplog.records if r.name == LOGGER and r.levelno == level]


def test_private_file_inside_checkout_logs_path_once_and_never_warns(tmp_path, monkeypatch, caplog):
    """Defect: a silent load (no INFO path), a repeated INFO per bridge, or a
    false warning on the recommended layout. Fails on the INFO count or the
    empty WARNING list."""
    monkeypatch.setattr(credential_environment, "checkout_root", lambda: tmp_path)
    path = _dotenv(tmp_path, 0o600)

    assert load_compatibility_dotenv(path) is True
    assert load_compatibility_dotenv(path) is True

    infos = _records(caplog, logging.INFO)
    assert len(infos) == 1 and str(path.resolve()) in infos[0]
    assert _records(caplog, logging.WARNING) == []
    assert os.environ[FAKE_NAME] == FAKE_VALUE
    assert FAKE_VALUE not in caplog.text


def test_file_outside_checkout_warns_with_both_paths(tmp_path, monkeypatch, caplog):
    """Defect F1: an ancestor ``.env`` (e.g. the main checkout's, seen from a
    worktree) is imported silently. Fails if no WARNING names the file as
    outside the checkout."""
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.setattr(credential_environment, "checkout_root", lambda: checkout)
    path = _dotenv(tmp_path / "ancestor", 0o600)

    load_compatibility_dotenv(path)

    [warning] = _records(caplog, logging.WARNING)
    assert "outside the SIDERIUS checkout" in warning
    assert str(path.resolve()) in warning and str(checkout.resolve()) in warning
    assert FAKE_VALUE not in caplog.text


def test_group_readable_file_warns_with_mode(tmp_path, monkeypatch, caplog):
    """Defect: a group-readable 0640 secrets file inside the checkout passes unnoticed.
    Fails if no WARNING reports the permissive mode."""
    monkeypatch.setattr(credential_environment, "checkout_root", lambda: tmp_path)
    path = _dotenv(tmp_path, 0o640)

    load_compatibility_dotenv(path)

    [warning] = _records(caplog, logging.WARNING)
    assert "mode 640" in warning and "chmod 600" in warning
    assert FAKE_VALUE not in caplog.text


def test_existing_variable_wins_and_disabled_loading_reports_nothing(tmp_path, monkeypatch, caplog):
    """Defect: the wrapper changed precedence (override) or reported a file
    python-dotenv did not load. Fails on the preserved value or on any log."""
    monkeypatch.setattr(credential_environment, "checkout_root", lambda: tmp_path)
    path = _dotenv(tmp_path, 0o644)
    monkeypatch.setenv(FAKE_NAME, "from-shell")

    load_compatibility_dotenv(path)
    assert os.environ[FAKE_NAME] == "from-shell"

    caplog.clear()
    monkeypatch.setattr(credential_environment, "_REPORTED_DOTENV_PATHS", set())
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    assert load_compatibility_dotenv(path) is False
    assert [r for r in caplog.records if r.name == LOGGER] == []


def test_blank_provider_key_warns_by_name_without_value(monkeypatch, caplog):
    """Defect R9: ``GEMINI_API_KEY=" "`` passes the unset-key refusal and
    fails later as an opaque 401. Fails if no WARNING names the variable, or
    if a non-blank fake key also warns or appears in the log."""
    monkeypatch.setenv("GEMINI_API_KEY", "   ")
    assert _provider_credential_or_refuse("gemini", _KNOWN_PROVIDERS["gemini"]) == "   "
    [warning] = _records(caplog, logging.WARNING)
    assert "GEMINI_API_KEY is set but empty or whitespace-only" in warning

    caplog.clear()
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_VALUE)
    _provider_credential_or_refuse("gemini", _KNOWN_PROVIDERS["gemini"])
    assert _records(caplog, logging.WARNING) == []
    assert FAKE_VALUE not in caplog.text


def test_default_search_starts_at_the_bridge_module_directory(tmp_path, monkeypatch):
    """Backward compatibility: the bridge's former bare ``load_dotenv()``
    searched upward from ``src/agent``. Fails if the default search starts
    anywhere else (e.g. ``find_dotenv(usecwd=True)`` would start at the CWD).
    The walk is stubbed, so no real file is examined."""
    import dotenv.main

    starts: list[str] = []

    def record(path):
        starts.append(path)
        return iter(())

    monkeypatch.setattr(dotenv.main, "_walk_to_root", record)
    monkeypatch.setattr(sys, "gettrace", lambda: None)  # coverage would force CWD
    monkeypatch.chdir(tmp_path)

    assert load_compatibility_dotenv() is False
    expected = Path(llm_bridge.__file__).resolve().parent
    assert [Path(p) for p in starts] == [expected]
