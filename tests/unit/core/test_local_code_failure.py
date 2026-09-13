"""Package failure identity and fresh launch ownership, without process mocks."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from core.generated_library import bind_generated_library_to_workspace
from core.local_code import (
    CodePackageDeclaration,
    LocalCodeError,
    bind_code_package,
    capture_package,
)
from core.local_code.child import main, prepare_child
from core.local_code.failure import (
    FAILURE_ENV,
    REFUSAL_EXIT,
    code_package_failure,
    publish_failure,
    read_failure,
)
from core.subprocess_env import subprocess_env


def package_and_env(tmp_path, monkeypatch):
    (tmp_path / "helper.py").write_text("VALUE = 3\n")
    package = capture_package(CodePackageDeclaration(root=".", files=("helper.py",)), tmp_path)
    env = {}
    bind_generated_library_to_workspace(str(tmp_path / "workspace"), environ=env)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return package


def test_only_explicit_cause_preserves_failure_identity():
    original = LocalCodeError("missing declared helper")
    wrapped = ValueError("family wrapper")
    wrapped.__cause__ = original
    assert code_package_failure(wrapped) is original
    unrelated = RuntimeError("ordinary candidate failure")
    unrelated.__context__ = original
    assert code_package_failure(unrelated) is None
    wrapped.__cause__ = wrapped
    assert code_package_failure(wrapped) is None


def test_fresh_launch_reports_are_correlated_and_old_ambient_state_is_not_reused(
    tmp_path, monkeypatch
):
    package = package_and_env(tmp_path, monkeypatch)
    with bind_code_package(package):
        first = prepare_child([sys.executable, "-m", "json.tool"], subprocess_env())
        monkeypatch.setenv(FAILURE_ENV, first.env[FAILURE_ENV])
        second = prepare_child([sys.executable, "-m", "json.tool"], subprocess_env())
    assert first.channel != second.channel
    assert first.channel is not None and second.channel is not None
    publish_failure(first.channel, LocalCodeError("first launch refused"))
    second.check()
    with pytest.raises(LocalCodeError, match="first launch refused") as raised:
        first.check()
    assert raised.value.report.package_digest == package.identity.digest
    # An existing report with a different launch id must never satisfy this launch.
    second.channel.report_path.write_bytes(first.channel.report_path.read_bytes())
    with pytest.raises(LocalCodeError, match="launch/package identity"):
        second.check()


def test_guard_catches_explicit_family_wrapper_and_keeps_first_refusal(tmp_path, monkeypatch):
    package = package_and_env(tmp_path, monkeypatch)
    target = tmp_path / "target.py"
    target.write_text(
        "from core.local_code import LocalCodeError\n"
        "try: raise LocalCodeError('undeclared relative dependency')\n"
        "except LocalCodeError as exc: raise ValueError('family wrapper') from exc\n"
    )
    monkeypatch.setattr(sys, "argv", list(sys.argv))
    with bind_code_package(package):
        invocation = prepare_child([sys.executable, str(target)], subprocess_env())
        for key, value in invocation.env.items():
            monkeypatch.setenv(key, value)
        assert main(["script", str(target)]) == REFUSAL_EXIT
    assert invocation.channel is not None
    report = read_failure(invocation.channel)
    assert report.detail == "undeclared relative dependency"
    publish_failure(invocation.channel, LocalCodeError("later sibling error"))
    assert read_failure(invocation.channel) == report
    invocation.channel.report_path.write_text(json.dumps({"detail": "incomplete"}))
    with pytest.raises(LocalCodeError, match="failure report refused"):
        invocation.check()


def test_no_package_invocation_and_explicit_absence_keep_old_contract(tmp_path, monkeypatch):
    from core.local_code import root_code_scope

    command = ["external-command", "--unchanged"]
    env = {"A": "one"}
    invocation = prepare_child(command, env)
    assert invocation.argv == command and invocation.env == env
    assert invocation.channel is None
    monkeypatch.setenv(FAILURE_ENV, "stale invalid descriptor")
    with root_code_scope():
        assert FAILURE_ENV not in subprocess_env()
    assert not list(Path(tmp_path).iterdir())


def test_explicit_initializer_cannot_replace_inherited_locator_transport(tmp_path, monkeypatch):
    from core.local_code import binding, bootstrap_code_package
    from core.local_code.transport import DIGEST_ENV, MANIFEST_ENV

    package = package_and_env(tmp_path, monkeypatch)
    relocated = tmp_path / "relocated"
    relocated.mkdir()
    (relocated / "helper.py").write_bytes((tmp_path / "helper.py").read_bytes())
    other = capture_package(CodePackageDeclaration(root=".", files=("helper.py",)), relocated)
    assert other.identity == package.identity
    with bind_code_package(package):
        original = prepare_child([sys.executable, "-m", "json.tool"], subprocess_env())
    with bind_code_package(other):
        alternative = subprocess_env()
    for key, value in original.env.items():
        monkeypatch.setenv(key, value)
    # Model the fresh initializer's decision, not a new root masking inheritance.
    token = binding._ACTIVE.set(binding.UNBOUND)
    try:
        with pytest.raises(LocalCodeError, match="initializer transport differs"):
            bootstrap_code_package(alternative[MANIFEST_ENV], alternative[DIGEST_ENV])
        assert binding._ACTIVE.get() is binding.UNBOUND
    finally:
        binding._ACTIVE.reset(token)


def test_lazy_package_import_inside_pydantic_validator_is_not_candidate_validation(tmp_path):
    from pydantic import ValidationError

    from core.local_code import acquire_module

    entry = tmp_path / "config.py"
    entry.write_text(
        "from pydantic import BaseModel, field_validator\n"
        "class Config(BaseModel):\n"
        " value: int\n"
        " @field_validator('value')\n"
        " @classmethod\n"
        " def require_helper(cls, value):\n"
        "  from .undeclared import validate\n"
        "  return validate(value)\n"
    )
    package = capture_package(CodePackageDeclaration(root=".", files=("config.py",)), tmp_path)
    with bind_code_package(package), acquire_module(entry) as module:
        with pytest.raises(LocalCodeError, match="undeclared relative import"):
            module.Config(value=3)
        with pytest.raises(ValidationError):
            module.Config(value="not an integer")
