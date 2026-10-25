"""Real process/entry witnesses; no scientific child, API, or GPU execution."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from core.native_writer import WriterRefusal, inspect_writer
from core.native_writer.ownership import acquire

ROOT = Path(__file__).resolve().parents[4]


def _wait_json(path, process):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if path.exists():
            return json.loads(path.read_text())
        assert process.poll() is None, (
            process.stderr.read().decode() if process.stderr else "owner exited"
        )
        time.sleep(0.02)
    pytest.fail("child readiness deadline exceeded")


def test_killed_native_parent_leaves_claim_after_all_lock_holders_die(tmp_path):
    """A live independent child outlasts owner/iteration; free flock cannot grant restart."""
    workspace = tmp_path / "run"
    ready = tmp_path / "ready.json"
    probe = tmp_path / "native_probe.py"
    child_code = (
        "import json, os, time; from pathlib import Path; "
        f"Path({str(ready)!r}).write_text(json.dumps([os.getppid(), os.getpid()])); "
        "time.sleep(60)"
    )
    probe.write_text(
        "import json, os, sys\n"
        "from workflows import run_one_iteration as native\n"
        "from core.runtime_control.observed_subprocess import supervise_process\n"
        "def body(*args, **kwargs):\n"
        f"    code = {child_code!r}\n"
        "    supervise_process([sys.executable, '-c', code], env=dict(os.environ), "
        "preexec_fn=os.setsid, capture_stdout=True)\n"
        "native._run_owned_iteration = body\n"
        "native.main(sys.argv[1:])\n"
    )
    argv = [
        sys.executable,
        "-m",
        "core.native_writer",
        "launch",
        "--workspace",
        str(workspace),
        "--capture-sha256",
        "a" * 64,
        "--",
        sys.executable,
        str(probe),
        "--workspace",
        str(workspace),
        "--run_name",
        "ownership",
        "--start_iteration",
        "1",
        "--task_composition",
        str(ROOT / "configs/task_composition/quickstart.yaml"),
        "--data_dir",
        str(tmp_path),
    ]
    owner = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    participant = child = None
    try:
        participant, child = _wait_json(ready, owner)
        with pytest.raises(WriterRefusal, match="writer_active"):
            acquire(workspace)
        owner.kill()
        owner.wait(timeout=5)
        os.kill(participant, signal.SIGKILL)
        deadline = time.monotonic() + 5
        while inspect_writer(workspace).status == "active" and time.monotonic() < deadline:
            time.sleep(0.02)
        assert inspect_writer(workspace).status == "unresolved"
        os.kill(child, 0)  # Independent phase writer is still alive after flock release.
        with pytest.raises(WriterRefusal, match="writer_unresolved"):
            acquire(workspace)
        assert not workspace.exists()
    finally:
        for pid in (participant, child):
            if pid is not None:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        if owner.poll() is None:
            owner.kill()
        owner.wait(timeout=5)
        if owner.stderr:
            owner.stderr.close()


def test_slurm_first_job_enters_native_before_submission_finishes(tmp_path):
    """Keeping the submitter lock or exporting its private FD blocks the first job."""
    workspace = tmp_path / "run"
    evidence = tmp_path / "jobs.jsonl"
    sbatch = tmp_path / "sbatch"
    sbatch.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "from workflows import run_one_iteration as native\n"
        "assert 'SIDERIUS_NATIVE_WRITER' not in os.environ\n"
        "args = sys.argv[sys.argv.index('--siderius-checkout') + 2:]\n"
        "def body(*a, **k):\n"
        f"    with Path({str(evidence)!r}).open('a') as out:\n"
        "        out.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "native._run_owned_iteration = body\n"
        "native.main(args)\n"
        "print('Submitted batch job ' + args[args.index('--start_iteration') + 1])\n"
    )
    sbatch.chmod(0o700)
    env = dict(os.environ, PATH=f"{tmp_path}:{os.environ['PATH']}")
    proc = subprocess.run(
        [
            "bash",
            str(ROOT / "scripts/launch/run_chain.sh"),
            "--mode",
            "sdsc",
            "--workspace",
            str(workspace),
            "--run_name",
            "ownership",
            "--num_iterations",
            "2",
            "--task_composition",
            str(ROOT / "configs/task_composition/quickstart.yaml"),
            "--data_dir",
            str(tmp_path),
            "--no_auto_resume",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    jobs = [json.loads(line) for line in evidence.read_text().splitlines()]
    assert len(jobs) == 2
    assert not any(arg.startswith("--dependency") for arg in jobs[0])
    assert "--dependency=afterany:1" in jobs[1]
    assert inspect_writer(workspace).status == "unregistered"


def test_owner_forwards_signal_in_same_session_and_releases_clean_child(tmp_path):
    """A wrapper swallowing TERM or detaching sessions would time out or mismatch."""
    workspace = tmp_path / "run"
    ready = tmp_path / "ready.json"
    child = (
        "import json, os, signal, sys; from pathlib import Path; "
        "signal.signal(signal.SIGTERM, lambda *args: sys.exit(7)); "
        f"Path({str(ready)!r}).write_text(json.dumps(os.getsid(0))); signal.pause()"
    )
    owner = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "core.native_writer",
            "launch",
            "--workspace",
            str(workspace),
            "--capture-sha256",
            "a" * 64,
            "--",
            sys.executable,
            "-c",
            child,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        assert _wait_json(ready, owner) == os.getsid(0)
        owner.send_signal(signal.SIGTERM)
        assert owner.wait(timeout=5) == 7
        assert inspect_writer(workspace).status == "registered_idle"
    finally:
        if owner.poll() is None:
            owner.kill()
        owner.wait(timeout=5)
        if owner.stderr:
            owner.stderr.close()
