from __future__ import annotations

import pytest

from tests.helpers.configured_resource import (
    require_configured_directory,
    require_resource_file,
)

ENV_VAR = "SIDERIUS_TEST_OPTIONAL_RESOURCE"


def test_unconfigured_optional_resource_skips(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    with pytest.raises(pytest.skip.Exception, match="not configured"):
        require_configured_directory(ENV_VAR, requested_by="qualification")


@pytest.mark.parametrize("value", ["", "   "])
def test_explicit_blank_resource_fails(monkeypatch, value):
    monkeypatch.setenv(ENV_VAR, value)
    with pytest.raises(pytest.fail.Exception, match="configured but blank"):
        require_configured_directory(ENV_VAR, requested_by="qualification")


def test_explicit_missing_resource_fails(monkeypatch, tmp_path):
    missing = tmp_path / "missing"
    monkeypatch.setenv(ENV_VAR, str(missing))
    with pytest.raises(pytest.fail.Exception, match=r"configured.*does not exist"):
        require_configured_directory(ENV_VAR, requested_by="qualification")


def test_relative_resource_root_fails(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "relative/data")
    with pytest.raises(pytest.fail.Exception, match="must be an absolute path"):
        require_configured_directory(ENV_VAR, requested_by="qualification")


def test_directory_contract_rejects_a_file(monkeypatch, tmp_path):
    file_path = tmp_path / "not-a-directory"
    file_path.write_text("fixture", encoding="utf-8")
    monkeypatch.setenv(ENV_VAR, str(file_path))
    with pytest.raises(pytest.fail.Exception, match="not a directory"):
        require_configured_directory(ENV_VAR, requested_by="qualification")


def test_valid_directory_is_returned(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_VAR, str(tmp_path))
    assert require_configured_directory(ENV_VAR, requested_by="qualification") == tmp_path


def test_required_file_must_exist(tmp_path):
    with pytest.raises(pytest.fail.Exception, match="file does not exist"):
        require_resource_file(tmp_path, "missing.bin", requested_by="qualification")


@pytest.mark.parametrize("path", ["../outside.bin", "/tmp/outside.bin"])
def test_required_file_cannot_escape_its_configured_root(tmp_path, path):
    with pytest.raises(pytest.fail.Exception, match="must be relative"):
        require_resource_file(tmp_path, path, requested_by="qualification")


def test_required_file_symlink_cannot_escape_its_configured_root(tmp_path):
    outside = tmp_path.parent / "outside.bin"
    outside.write_bytes(b"outside")
    link = tmp_path / "linked.bin"
    link.symlink_to(outside)

    with pytest.raises(pytest.fail.Exception, match="resolves outside"):
        require_resource_file(tmp_path, link.name, requested_by="qualification")


def test_required_file_rejects_a_directory(tmp_path):
    directory = tmp_path / "directory.bin"
    directory.mkdir()
    with pytest.raises(pytest.fail.Exception, match="not a file"):
        require_resource_file(tmp_path, directory.name, requested_by="qualification")


def test_valid_required_file_is_returned(tmp_path):
    file_path = tmp_path / "resource.bin"
    file_path.write_bytes(b"fixture")
    assert (
        require_resource_file(tmp_path, file_path.name, requested_by="qualification") == file_path
    )
