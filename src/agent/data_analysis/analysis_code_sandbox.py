"""Fail-closed Linux isolation for untrusted experiment-local analysis code."""

from __future__ import annotations

import hashlib
import os
import resource
import shutil
import signal
import site
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import psutil

from agent.schemas.data_analysis.common import canonical_json_bytes, utc_now
from agent.schemas.data_analysis.generated_program import GeneratedAnalysisProgram
from agent.schemas.data_analysis.resources import ResourceUsage
from agent.schemas.data_analysis.skills import SkillPayload
from core.campaign_identity import validate_path_component
from core.durable_io import publish_bytes_write_once
from core.runtime_control.process_group import process_group_alive

SANDBOX_PROTOCOL_ID = "siderius.generated-analysis-sandbox.v1"
MAX_GENERATED_PAYLOAD_BYTES = 1024 * 1024
GENERATED_PROCESS_HEADROOM = 64


class AnalysisCodeSandboxUnavailable(RuntimeError):
    """The host cannot enforce the generated-code trust boundary."""


class AnalysisCodeSandboxError(RuntimeError):
    """Generated code failed inside an available isolation boundary."""


@dataclass(frozen=True)
class SandboxCapabilityReceipt:
    available: bool
    protocol_id: str
    bubblewrap_path: str | None
    unshare_path: str | None
    reason: str | None = None


@dataclass(frozen=True)
class SandboxExecutionReceipt:
    status: Literal[
        "completed",
        "failed",
        "timed_out",
        "memory_limit_exceeded",
        "output_limit_exceeded",
    ]
    resource_usage: ResourceUsage
    payload: SkillPayload | None
    failure_type: str | None
    failure_message: str | None
    worker_pid: int
    started_at: str
    finished_at: str
    stdout_sha256: str
    stderr_sha256: str


def _sandbox_preexec(
    *,
    max_address_space_bytes: int,
    cpu_seconds: int,
    uid_process_limit: int,
) -> None:
    resource.setrlimit(resource.RLIMIT_AS, (max_address_space_bytes, max_address_space_bytes))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024 * 1024, 64 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    resource.setrlimit(resource.RLIMIT_NPROC, (uid_process_limit, uid_process_limit))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _current_uid_task_count() -> int:
    """Count the host-UID task baseline used by RLIMIT_NPROC before user unshare."""

    uid = os.getuid()
    count = 0
    for process in psutil.process_iter(("uids",)):
        try:
            uids = process.info["uids"]
            if uids is not None and uids.real == uid:
                count += process.num_threads()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return count


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 1.0
    while process_group_alive(process.pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    if not process_group_alive(process.pid):
        if process.poll() is None:
            process.wait(timeout=1.0)
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    if process.poll() is None:
        process.wait(timeout=2.0)


def _process_tree_rss(process: psutil.Process) -> int:
    total = 0
    try:
        processes = (process, *process.children(recursive=True))
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return 0
    for item in processes:
        try:
            total += item.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return total


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_tail(path: Path, *, max_bytes: int = 2048) -> str:
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(max(0, size - max_bytes))
        return stream.read(max_bytes).decode("utf-8", errors="replace")


def _output_tree_exceeds(
    path: Path,
    *,
    max_nodes: int,
    max_bytes: int,
) -> bool:
    count = 0
    total_bytes = 0
    pending = [path]
    while pending:
        directory = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except FileNotFoundError:
            continue
        for item in entries:
            count += 1
            if count > max_nodes:
                return True
            try:
                if item.is_dir(follow_symlinks=False):
                    pending.append(Path(item.path))
                elif item.is_file(follow_symlinks=False):
                    total_bytes += item.stat(follow_symlinks=False).st_size
                    if total_bytes > max_bytes:
                        return True
            except FileNotFoundError:
                continue
    return False


class AnalysisCodeSandbox:
    """Execute one validated program with only explicit read/write mounts."""

    def __init__(self) -> None:
        self._bubblewrap = shutil.which("bwrap")
        self._unshare = shutil.which("unshare")
        self._python_executable = Path(sys.executable).resolve()
        self._python_root = self._python_executable.parents[1]
        self._sandbox_python = f"/runtime/python/bin/{self._python_executable.name}"
        self._venv_root = Path(sys.prefix).resolve()
        self._site_packages = self._resolve_site_packages()
        self._sandbox_site_packages = (
            Path("/runtime/venv") / self._site_packages.relative_to(self._venv_root)
        ).as_posix()
        self._runner = Path(__file__).resolve().with_name("generated_program_runner.py")

    def _resolve_site_packages(self) -> Path:
        candidates = [Path(item).resolve() for item in site.getsitepackages()]
        for candidate in candidates:
            if self._venv_root in candidate.parents and candidate.is_dir():
                return candidate
        raise AnalysisCodeSandboxUnavailable("the active environment has no local site-packages")

    def _clean_environment(self) -> dict[str, str]:
        return {
            "HOME": "/nonexistent",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": "/runtime/python/bin",
            "PYTHONPATH": self._sandbox_site_packages,
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
        }

    def _base_command(self) -> list[str]:
        assert self._bubblewrap is not None
        assert self._unshare is not None
        command = [
            self._unshare,
            "--user",
            "--map-root-user",
            "--net",
            self._bubblewrap,
            "--unshare-pid",
            "--unshare-ipc",
            "--unshare-uts",
            "--die-with-parent",
            "--new-session",
            "--dir",
            "/runtime",
            "--ro-bind",
            str(self._python_root),
            "/runtime/python",
            "--ro-bind",
            str(self._venv_root),
            "/runtime/venv",
        ]
        for library_root in (Path("/lib"), Path("/lib64"), Path("/usr/lib")):
            if library_root.exists():
                command.extend(("--ro-bind", str(library_root), str(library_root)))
        command.extend(
            [
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                "--tmpfs",
                "/tmp",
            ]
        )
        for key, value in self._clean_environment().items():
            command.extend(("--setenv", key, value))
        return command

    def probe(self) -> SandboxCapabilityReceipt:
        if self._bubblewrap is None or self._unshare is None:
            return SandboxCapabilityReceipt(
                available=False,
                protocol_id=SANDBOX_PROTOCOL_ID,
                bubblewrap_path=self._bubblewrap,
                unshare_path=self._unshare,
                reason="bubblewrap and unshare are both required",
            )
        try:
            with tempfile.TemporaryDirectory(prefix="siderius-analysis-sandbox-probe-") as temp:
                output = Path(temp)
                command = [
                    *self._base_command(),
                    "--bind",
                    str(output),
                    "/output",
                    "--chdir",
                    "/tmp",
                    "--",
                    self._sandbox_python,
                    "-c",
                    (
                        "import os,socket,numpy as np;"
                        "assert not os.path.exists('/home');"
                        "assert 'OPENAI_API_KEY' not in os.environ;"
                        "open('/output/probe','w').write(np.__version__);"
                        "\ntry: s=socket.socket()\n"
                        "except OSError: pass\n"
                        "else:\n"
                        " s.settimeout(0.25)\n"
                        " try: s.connect(('198.51.100.1', 9))\n"
                        " except OSError: pass\n"
                        " else: raise RuntimeError('external network unexpectedly reachable')\n"
                        " finally: s.close()"
                    ),
                ]
                completed = subprocess.run(
                    command,
                    env=self._clean_environment(),
                    capture_output=True,
                    timeout=10.0,
                    check=False,
                )
                if completed.returncode != 0 or not (output / "probe").is_file():
                    detail = completed.stderr.decode("utf-8", errors="replace")[-512:]
                    raise RuntimeError(detail or f"probe exited {completed.returncode}")
        except Exception as exc:
            return SandboxCapabilityReceipt(
                available=False,
                protocol_id=SANDBOX_PROTOCOL_ID,
                bubblewrap_path=self._bubblewrap,
                unshare_path=self._unshare,
                reason=str(exc) or type(exc).__name__,
            )
        return SandboxCapabilityReceipt(
            available=True,
            protocol_id=SANDBOX_PROTOCOL_ID,
            bubblewrap_path=self._bubblewrap,
            unshare_path=self._unshare,
        )

    def execute(
        self,
        *,
        program: GeneratedAnalysisProgram,
        source_path: Path,
        materialization_paths: dict[str, str],
        materialization_descriptors: dict[str, dict[str, Any]],
        parameters: dict[str, Any],
        output_directory: Path,
        control_directory: Path,
        timeout_s: float,
        max_host_memory_gb: float,
    ) -> SandboxExecutionReceipt:
        capability = self.probe()
        if not capability.available:
            raise AnalysisCodeSandboxUnavailable(capability.reason or "sandbox unavailable")
        for path, label in (
            (source_path, "generated source"),
            (self._runner, "sandbox runner"),
        ):
            if path.is_symlink() or not path.is_file():
                raise AnalysisCodeSandboxError(f"{label} must be a regular non-symlink file")
        source_bytes = source_path.read_bytes()
        if len(source_bytes) != program.source_ref.byte_size:
            raise AnalysisCodeSandboxError("generated source byte size differs from declaration")
        if hashlib.sha256(source_bytes).hexdigest() != program.source_sha256:
            raise AnalysisCodeSandboxError("generated source digest differs from declaration")
        if output_directory.is_symlink() or not output_directory.is_dir():
            raise AnalysisCodeSandboxError("output directory must be executor-created")
        if any(output_directory.iterdir()):
            raise AnalysisCodeSandboxError("output directory must be empty before execution")
        control_directory.mkdir(parents=True, exist_ok=False)
        request_path = control_directory / "request.json"
        sandbox_inputs: dict[str, dict[str, Any]] = {}
        input_mounts: list[str] = []
        if set(materialization_paths) != set(materialization_descriptors):
            raise AnalysisCodeSandboxError(
                "materialization paths and certified descriptors must have identical bindings"
            )
        for binding_id, raw_path in sorted(materialization_paths.items()):
            safe_id = validate_path_component(binding_id, kind="generated program binding id")
            path = Path(raw_path).resolve()
            if path.is_symlink() or not path.is_file():
                raise AnalysisCodeSandboxError(
                    f"materialization {binding_id!r} must be a regular non-symlink file"
                )
            sandbox_path = f"/inputs/{safe_id}.materialized"
            input_mounts.extend(("--ro-bind", str(path), sandbox_path))
            sandbox_inputs[binding_id] = {
                **materialization_descriptors[binding_id],
                "path": sandbox_path,
            }
        publish_bytes_write_once(
            str(request_path),
            canonical_json_bytes(
                {
                    "inputs": sandbox_inputs,
                    "parameters": parameters,
                    "determinism": program.determinism,
                    "seed": program.seed,
                    "output_directory": "/output",
                }
            ),
        )
        payload_path = output_directory / "payload.json"
        command = [
            *self._base_command(),
            "--dir",
            "/runner",
            "--dir",
            "/program",
            "--dir",
            "/request",
            "--dir",
            "/inputs",
            "--ro-bind",
            str(self._runner),
            "/runner/runner.py",
            "--ro-bind",
            str(source_path),
            "/program/program.py",
            "--ro-bind",
            str(request_path),
            "/request/request.json",
            *input_mounts,
            "--bind",
            str(output_directory),
            "/output",
            "--chdir",
            "/program",
            "--",
            self._sandbox_python,
            "/runner/runner.py",
            "--source",
            "/program/program.py",
            "--request",
            "/request/request.json",
            "--output",
            "/output/payload.json",
        ]
        started_at = utc_now()
        started = time.monotonic()
        uid_process_limit = _current_uid_task_count() + GENERATED_PROCESS_HEADROOM
        stdout_path = control_directory / "stdout.log"
        stderr_path = control_directory / "stderr.log"
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(
                command,
                env=self._clean_environment(),
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
                preexec_fn=lambda: _sandbox_preexec(
                    max_address_space_bytes=max(1, int(max_host_memory_gb * 1024**3)),
                    cpu_seconds=max(1, int(timeout_s) + 1),
                    uid_process_limit=uid_process_limit,
                ),
            )
            ps_process = psutil.Process(process.pid)
            peak_rss = 0
            disposition: Literal[
                "completed",
                "failed",
                "timed_out",
                "memory_limit_exceeded",
                "output_limit_exceeded",
            ] = "failed"
            memory_limit = int(max_host_memory_gb * 1024**3)
            output_byte_limit = (
                program.resource_request.max_artifact_bytes + MAX_GENERATED_PAYLOAD_BYTES
            )
            output_node_limit = max(16, program.resource_request.max_artifact_count * 4 + 8)
            while process.poll() is None:
                elapsed = time.monotonic() - started
                peak_rss = max(peak_rss, _process_tree_rss(ps_process))
                if peak_rss > memory_limit:
                    disposition = "memory_limit_exceeded"
                    _terminate_process_group(process)
                    break
                if _output_tree_exceeds(
                    output_directory,
                    max_nodes=output_node_limit,
                    max_bytes=output_byte_limit,
                ):
                    disposition = "output_limit_exceeded"
                    _terminate_process_group(process)
                    break
                if elapsed >= timeout_s:
                    disposition = "timed_out"
                    _terminate_process_group(process)
                    break
                time.sleep(0.02)
            if process_group_alive(process.pid):
                _terminate_process_group(process)
            process.wait(timeout=2.0)
        peak_rss = max(peak_rss, _process_tree_rss(ps_process))
        wall_time = max(0.0, time.monotonic() - started)
        if disposition not in {
            "timed_out",
            "memory_limit_exceeded",
            "output_limit_exceeded",
        }:
            disposition = "completed" if process.returncode == 0 else "failed"
        payload: SkillPayload | None = None
        failure_type: str | None = None
        failure_message: str | None = None
        if disposition == "completed":
            try:
                if payload_path.is_symlink() or not payload_path.is_file():
                    raise ValueError("sandbox did not produce a regular payload file")
                if payload_path.stat().st_size > MAX_GENERATED_PAYLOAD_BYTES:
                    raise ValueError("generated payload exceeds its bounded JSON limit")
                payload = SkillPayload.model_validate_json(payload_path.read_bytes())
            except Exception as exc:
                disposition = "failed"
                failure_type = "invalid_generated_payload"
                failure_message = str(exc) or type(exc).__name__
        else:
            failure_type = disposition
            failure_message = _read_tail(stderr_path) or disposition
        return SandboxExecutionReceipt(
            status=disposition,
            resource_usage=ResourceUsage(
                wall_time_s=wall_time,
                peak_rss_bytes=peak_rss,
                device="cpu",
                measurement_limitations=(
                    "CPU time was not measured per process group.",
                    "RLIMIT_AS bounds virtual address space; peak RSS is observed separately.",
                    "RLIMIT_NPROC is host-UID-scoped and permits a fixed increment above the "
                    "observed pre-launch UID task baseline.",
                ),
            ),
            payload=payload,
            failure_type=failure_type,
            failure_message=failure_message,
            worker_pid=process.pid,
            started_at=started_at,
            finished_at=utc_now(),
            stdout_sha256=_file_sha256(stdout_path),
            stderr_sha256=_file_sha256(stderr_path),
        )
