"""Private configuration publishers must exclude other processes through CAS/replace."""

import subprocess
import sys
from pathlib import Path

import pytest

from tests.unit.tools.candidate_console.test_settings_page import _client, _load, workspace
from tools.candidate_console.add_task import TaskPlan, publish_task
from tools.candidate_console.settings_service import _publish_private


def _assert_other_process_excluded(path: Path) -> None:
    """A second process must not enter this file's write transaction during publication."""
    probe = """
import fcntl, os, sys
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    sys.exit(73)
"""
    result = subprocess.run(
        [sys.executable, "-c", probe, str(path.with_name("." + path.name + ".lock"))],
        timeout=15,
        check=False,
    )
    assert result.returncode == 73, "another process entered the CAS-to-replace window"


@pytest.mark.parametrize("writer", ["setup", "add_task", "settings"])
def test_configuration_publish_excludes_other_process(writer, workspace, monkeypatch):
    """Fails when any cooperative writer permits a second process during final replace."""
    observed = []

    def publish(path, payload):
        _assert_other_process_excluded(path)
        observed.append(path.name)
        return _publish_private(path, payload)

    monkeypatch.setattr("tools.candidate_console.settings_service._publish_private", publish)
    if writer == "add_task":
        path = workspace / "settings" / "console.json"
        current = path.read_bytes()
        publish_task(TaskPlan(path, current, {}, current + b"\n", workspace))
        assert path.read_bytes() == current + b"\n"
    else:
        api = _client(_load(workspace))
        if writer == "setup":
            response = api.post("/api/tasks/synthetic/setups", json={"label": "Concurrent"})
            assert response.status_code == 201, response.text
        else:
            response = api.put(
                "/api/settings",
                json={
                    "expected_sha256": api.get("/api/settings").json()["settings_sha256"],
                    "settings": _load(workspace).settings.settings.model_dump(mode="json"),
                },
            )
            assert response.status_code == 200, response.text
    assert len(observed) == 1


def test_waiting_add_task_rechecks_bytes_after_lock_acquisition(tmp_path):
    """A writer that waits must reject a predecessor's change, not overwrite it."""
    import select

    from tools.candidate_console.files import private_file_lock

    path = tmp_path / "console.json"
    path.write_bytes(b"original")
    child = """
import fcntl, sys
from pathlib import Path
from tools.candidate_console.add_task import AddTaskRefused, TaskPlan, publish_task
path = Path(sys.argv[1])
plan = TaskPlan(path, b'original', {}, b'losing write', path.parent)
flock = fcntl.flock
def announce(fd, mode):
    print('locking', flush=True)
    return flock(fd, mode)
fcntl.flock = announce
try:
    publish_task(plan)
except AddTaskRefused:
    print('stale', flush=True)
else:
    print('overwritten', flush=True)
"""
    process = None
    try:
        with private_file_lock(path):
            process = subprocess.Popen(
                [sys.executable, "-c", child, str(path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            assert process.stdout is not None
            ready, _, _ = select.select([process.stdout], [], [], 15)
            assert ready, "writer never reached lock acquisition"
            assert process.stdout.readline().strip() == "locking"
            _publish_private(path, b"winning write")
        output, error = process.communicate(timeout=15)
        assert process.returncode == 0, error
        assert output.strip() == "stale"
        assert path.read_bytes() == b"winning write"
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate(timeout=15)


@pytest.mark.parametrize("kind", ["symlink", "fifo", "public", "hardlink"])
def test_configuration_lock_refuses_unsafe_inode(kind, tmp_path):
    """A linked, special or public lock must not split the writer exclusion boundary."""
    import os

    from tools.candidate_console.files import private_file_lock
    from tools.candidate_operations.models import OperationFailure

    path = tmp_path / "config.json"
    lock = tmp_path / ".config.json.lock"
    target = tmp_path / "target"
    target.write_bytes(b"unchanged")
    target.chmod(0o600)
    if kind == "symlink":
        lock.symlink_to(target)
    elif kind == "hardlink":
        os.link(target, lock)
    elif kind == "fifo":
        os.mkfifo(lock, 0o600)
    else:
        lock.write_bytes(b"")
        lock.chmod(0o644)
    with pytest.raises((OSError, OperationFailure)):
        with private_file_lock(path):
            pytest.fail("unsafe lock admitted")
    assert target.read_bytes() == b"unchanged"
