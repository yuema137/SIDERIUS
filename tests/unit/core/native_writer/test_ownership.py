"""Regression contracts: independent writers cannot share a supported native run."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from core.native_writer.models import WriterRefusal
from core.native_writer.ownership import TRANSPORT_ENV, acquire, inherit, inspect_writer
from tests.helpers.process_bounds import CHILD_PROCESS_BOUND_SECONDS

DIGEST = "a" * 64


def python(command, *args, **kwargs):
    return subprocess.run(
        [sys.executable, "-c", command, *map(str, args)],
        text=True,
        capture_output=True,
        timeout=CHILD_PROCESS_BOUND_SECONDS,
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


@pytest.mark.skipif(
    os.geteuid() == 0, reason="root ignores the mode bits simulating a read-only bind"
)
def test_prepared_state_holds_ownership_without_directory_write_access(tmp_path):
    """#1525: the candidate sandbox binds the prepared writer directory read-only,
    with only ``writer.lock`` writable on top.

    Mode 0500 on the directory stands in for that bind. Fails if
    ``prepare_state_directory`` stops pre-creating ``writer.lock`` (creating it then
    needs directory write access, EACCES).
    """
    from core.native_writer import iteration_owner
    from core.native_writer.state import prepare_state_directory

    workspace = tmp_path / "run"
    state = prepare_state_directory(workspace)
    state.chmod(0o500)
    try:
        with iteration_owner(str(workspace)) as lease:
            assert lease is not None and lease.claim is None
            loser = python(
                "from core.native_writer.ownership import acquire; import sys; acquire(sys.argv[1])",
                workspace,
            )
            assert loser.returncode != 0 and "writer_active" in loser.stderr
            assert inspect_writer(workspace).status == "active"
        assert inspect_writer(workspace).status == "unregistered"
    finally:
        state.chmod(0o700)


def test_exclusive_lock_works_where_flock_needs_a_writable_descriptor(tmp_path, monkeypatch):
    """#1525 review B1: NFS and SMB/CIFS emulate flock with fcntl whole-file locks,
    and an exclusive one refuses a read-only descriptor with EBADF. A native run on
    such a workspace would then refuse before starting (writer_state_refused).
    Models that filesystem; fails if ``open_lock`` opens the lock read-only."""
    import errno
    import fcntl

    from core.native_writer import iteration_owner, ownership

    real = fcntl.flock

    def nfs_flock(fd: int, operation: int) -> None:
        if operation & fcntl.LOCK_EX and (fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE) == (
            os.O_RDONLY
        ):
            raise OSError(errno.EBADF, "Bad file descriptor")
        real(fd, operation)

    monkeypatch.setattr(ownership.fcntl, "flock", nfs_flock)
    workspace = tmp_path / "run"
    with iteration_owner(str(workspace)) as lease:
        assert lease is not None
        assert fcntl.fcntl(lease.fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDWR
        assert inspect_writer(workspace).status == "active"
    assert inspect_writer(workspace).status == "unregistered"


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
