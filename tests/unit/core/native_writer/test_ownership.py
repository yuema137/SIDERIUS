"""Regression contracts: independent writers cannot share a supported native run."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from core.native_writer.models import WriterRefusal
from core.native_writer.ownership import TRANSPORT_ENV, acquire, inherit, inspect_writer

DIGEST = "a" * 64


def python(command, *args, **kwargs):
    return subprocess.run(
        [sys.executable, "-c", command, *map(str, args)],
        text=True,
        capture_output=True,
        timeout=10,
        **kwargs,
    )


def test_independent_root_refuses_but_inherited_description_joins(tmp_path):
    """A descriptor passed through exec joins; reopening the inode cannot impersonate it."""
    workspace = tmp_path / "run"
    lease = acquire(workspace, capture_sha256=DIGEST)
    env = dict(os.environ, **{TRANSPORT_ENV: lease.transport.model_dump_json()})
    try:
        loser = python(
            "from core.native_writer.ownership import acquire; import sys; acquire(sys.argv[1])",
            workspace,
        )
        assert loser.returncode != 0 and "writer_active" in loser.stderr
        child = python(
            "from core.native_writer.ownership import inherit,TRANSPORT_ENV; import os,sys; "
            "x=inherit(sys.argv[1],os.environ[TRANSPORT_ENV]); x.close(clean=True)",
            workspace,
            env=env,
            pass_fds=(lease.fd,),
        )
        assert child.returncode == 0, child.stderr
        forged = os.open(lease.state.path / "writer.lock", os.O_RDWR)
        try:
            transport = lease.transport.model_copy(update={"fd": forged})
            with pytest.raises(WriterRefusal, match="writer_descriptor_not_held"):
                inherit(workspace, transport.model_dump_json())
        finally:
            os.close(forged)
        assert not workspace.exists()
    finally:
        lease.close(clean=True)
    assert inspect_writer(workspace).status == "registered_idle"
    with pytest.raises(WriterRefusal, match="registered_owner_required"):
        acquire(workspace)


def test_dead_owner_claim_survives_kernel_release_and_forged_fd(tmp_path):
    """PID/lock absence cannot reopen registered work after an abrupt process exit."""
    workspace = tmp_path / "run"
    result = python(
        "from core.native_writer.ownership import acquire; import os,sys; "
        "x=acquire(sys.argv[1],capture_sha256=sys.argv[2]); "
        "print(x.transport.model_dump_json(),flush=True); os._exit(0)",
        workspace,
        DIGEST,
    )
    assert result.returncode == 0, result.stderr
    assert inspect_writer(workspace).status == "unresolved"
    with pytest.raises(WriterRefusal, match="writer_unresolved"):
        acquire(workspace, capture_sha256=DIGEST)
    forged = os.open(tmp_path / ".run.siderius-writer/writer.lock", os.O_RDWR)
    try:
        payload = json.loads(result.stdout)
        payload["fd"] = forged
        with pytest.raises(WriterRefusal, match="writer_descriptor_not_held"):
            inherit(workspace, json.dumps(payload))
    finally:
        os.close(forged)
    assert not workspace.exists()


def test_aliases_share_lock_and_unrelated_workspace_progresses(tmp_path):
    """Alias spelling must not create a second mutex; unrelated work must not serialize."""
    directory = tmp_path / "real"
    directory.mkdir()
    (tmp_path / "alias").symlink_to(directory, target_is_directory=True)
    lease = acquire(directory / "run")
    inode = os.fstat(lease.fd).st_ino
    try:
        with pytest.raises(WriterRefusal, match="writer_active"):
            acquire(tmp_path / "alias/run")
        other = acquire(directory / "other")
        other.close(clean=True)
    finally:
        lease.close(clean=True)
    again = acquire(directory / "run")
    try:
        assert os.fstat(again.fd).st_ino == inode
    finally:
        again.close(clean=True)


@pytest.mark.parametrize("damage", ["directory_link", "lock_link", "bad_claim", "missing_parent"])
def test_unsafe_state_refuses_before_scientific_directory(tmp_path, damage):
    """Unsafe or unreadable coordination cannot fall back to an unprotected writer."""
    workspace = tmp_path / "run"
    state = tmp_path / ".run.siderius-writer"
    if damage == "directory_link":
        target = tmp_path / "target"
        target.mkdir(mode=0o700)
        state.symlink_to(target, target_is_directory=True)
    elif damage == "missing_parent":
        workspace = tmp_path / "missing/run"
    else:
        state.mkdir(mode=0o700)
        if damage == "lock_link":
            (tmp_path / "target").touch(mode=0o600)
            (state / "writer.lock").symlink_to(tmp_path / "target")
        else:
            (state / "claim.json").write_text("broken")
            (state / "claim.json").chmod(0o600)
    with pytest.raises((OSError, ValueError, WriterRefusal)):
        acquire(workspace)
    assert not workspace.exists()


def test_inspection_absent_state_never_creates_control_or_workspace(tmp_path):
    workspace = tmp_path / "run"
    assert inspect_writer(workspace).status == "unregistered"
    assert list(tmp_path.iterdir()) == []


def test_legacy_delegation_requires_no_nonexistent_durable_claim(tmp_path):
    lease = acquire(tmp_path / "run")
    try:
        delegated = inherit(tmp_path / "run", lease.transport.model_dump_json())
        assert delegated.claim is None
        delegated.close(clean=True)
        assert not (lease.state.path / "claim.json").exists()
        assert not (lease.state.path / "registration.json").exists()
    finally:
        lease.close(clean=True)
