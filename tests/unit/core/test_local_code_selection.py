"""Scanner exclusion and immutable transport fail at their actual owners."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.generated_library import bind_generated_library_to_workspace
from core.local_code import (
    CodePackageDeclaration,
    LocalCodeError,
    bind_code_package,
    capture_package,
)
from core.local_code.capture import sha256
from core.local_code.transport import (
    DIGEST_ENV,
    MANIFEST_ENV,
    read_inherited_package,
    write_transport,
)


def test_transport_rejects_overwritten_artifact_and_noncanonical_pin_set(tmp_path):
    (tmp_path / "a.py").write_text("VALUE = 1\n")
    (tmp_path / "b.py").write_text("VALUE = 2\n")
    package = capture_package(CodePackageDeclaration(root=".", files=("a.py", "b.py")), tmp_path)
    env: dict[str, str] = {}
    bind_generated_library_to_workspace(str(tmp_path / "workspace"), environ=env)
    write_transport(package, env)
    manifest = Path(env[MANIFEST_ENV])
    original = manifest.read_bytes()
    manifest.write_bytes(b"not the captured manifest")
    with pytest.raises(LocalCodeError, match="immutable transport mismatch"):
        write_transport(package, env)
    assert manifest.read_bytes() == b"not the captured manifest"

    # Even a self-consistent outer hash cannot make a noncanonical member set
    # authoritative at the typed transport boundary.
    payload = json.loads(original)
    payload["identity"]["members"].reverse()
    malformed = json.dumps(payload).encode()
    manifest.write_bytes(malformed)
    env[DIGEST_ENV] = sha256(malformed)
    with pytest.raises(LocalCodeError, match="canonical member order"):
        read_inherited_package(env)


def test_objective_discovery_uses_captured_text_and_excludes_unlisted_shadow(tmp_path, monkeypatch):
    from ml_models import loss_plugin_loader
    from workflows.task_composition import (
        ResolvedPluginRef,
        _objective_name_declared_by,
        _refuse_ambiguous_objective,
    )

    entry = tmp_path / "loss.py"
    entry.write_text("PLUGIN_LOSS_TYPE = 'pinned_objective'\n")
    (tmp_path / "unlisted.py").write_text("PLUGIN_LOSS_TYPE = 'pinned_objective'\n")
    package = capture_package(CodePackageDeclaration(root=".", files=("loss.py",)), tmp_path)
    entry.write_text("PLUGIN_LOSS_TYPE = 'changed_disk'\n")
    monkeypatch.setattr(loss_plugin_loader, "_resolve_loss_dirs", lambda: [str(tmp_path)])
    with bind_code_package(package):
        assert _objective_name_declared_by(str(entry)) == "pinned_objective"
        ref = ResolvedPluginRef(
            "loss.py", "PLUGIN_LOSS_TYPE", package.members[0].pin.content_sha256, str(entry)
        )
        _refuse_ambiguous_objective("pinned_objective", ref, str(tmp_path), "objective")


@pytest.mark.parametrize("family", ["model", "loss"])
def test_global_preload_excludes_unlisted_before_explicit_registration(
    tmp_path, monkeypatch, family
):
    from core import generated_library
    from ml_models import loss_models_sandbox, plugin_loader

    (tmp_path / "listed.py").write_text("VALUE = 1\n")
    (tmp_path / "unlisted.py").write_text("raise AssertionError('not selected')\n")
    package = capture_package(CodePackageDeclaration(root=".", files=("listed.py",)), tmp_path)
    plural = "models" if family == "model" else "losses"
    monkeypatch.setattr(generated_library, "generated_library_is_workspace_bound", lambda: True)
    monkeypatch.setattr(generated_library, f"generated_{plural}_dir", lambda: str(tmp_path))
    owner = plugin_loader if family == "model" else loss_models_sandbox
    observed = []
    monkeypatch.setattr(
        owner,
        f"register_{family}_in_memory",
        lambda path, *_args, **_kwargs: observed.append(path),
    )
    with bind_code_package(package):
        getattr(owner, f"preload_global_{plural}")()
    assert observed == [str(tmp_path / "listed.py")]
