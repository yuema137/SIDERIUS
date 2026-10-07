"""Launch inspection shares runtime rules without importing execution owners."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

from workflows import literature_config
from workflows.launch_identity import resolve_lit_review_enabled


def test_import_and_disabled_identity_do_not_load_execution(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            """
import sys
from workflows import literature_config, runtime_settings
from workflows.launch_identity import resolve_lit_review_enabled
assert not resolve_lit_review_enabled(None, None)
assert literature_config.lit_review_config_sha256('/missing/config', enabled=False) is None
for name in ('workflows.run_one_iteration', 'workflows.model_exploration',
             'nodes', 'dotenv', 'agent.llm_bridge', 'openai'):
    assert name not in sys.modules, name
""",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert not list(tmp_path.iterdir())


def test_literature_path_and_digest_use_checkout_not_cwd(tmp_path, monkeypatch) -> None:
    checkout = tmp_path / "source checkout"
    checkout.mkdir()
    config = checkout / "review.yaml"
    content = b"enabled: true\r\nqueries: []\r\n"
    config.write_bytes(content)
    monkeypatch.setattr(literature_config, "SIDERIUS_ROOT", checkout)
    monkeypatch.chdir(tmp_path)
    assert literature_config.resolve_lit_review_config_path("review.yaml") == str(config)
    assert resolve_lit_review_enabled(None, "review.yaml") is True
    assert (
        literature_config.lit_review_config_sha256("review.yaml", enabled=True)
        == hashlib.sha256(content).hexdigest()
    )


def test_installed_literature_absolute_path_and_relative_refusal(tmp_path, monkeypatch) -> None:
    config = tmp_path / "review.yaml"
    config.write_text("enabled: false\n")
    monkeypatch.setattr(literature_config, "SIDERIUS_ROOT", None)
    assert literature_config.resolve_lit_review_config_path(str(config)) == str(config)
    assert literature_config.lit_review_config_sha256(str(config), enabled=True)
    with pytest.raises(FileNotFoundError, match="requires the SIDERIUS source checkout"):
        literature_config.resolve_lit_review_config_path("review.yaml")


def test_literature_disabled_and_invalid_config_errors(tmp_path) -> None:
    missing = str(tmp_path / "missing.yaml")
    assert literature_config.lit_review_config_sha256(missing, enabled=False) is None
    assert literature_config.lit_review_config_sha256(None, enabled=False) is None
    with pytest.raises(ValueError, match="enabled but no config was declared"):
        literature_config.lit_review_config_sha256(None, enabled=True)
    with pytest.raises(ValueError, match="cannot be read"):
        literature_config.lit_review_config_sha256(missing, enabled=True)
    assert not resolve_lit_review_enabled(None, missing)
    assert resolve_lit_review_enabled(True, missing)
