"""Capture shell-owned settings using existing isolated observation owners."""

from __future__ import annotations

import base64
import hashlib
import io
import os
import subprocess
import tempfile
from contextlib import redirect_stderr
from pathlib import Path

from core.durable_io import publish_bytes_write_once
from core.file_identity import open_identity_file, path_matches_snapshot, regular_file_snapshot
from core.layout import checkout_root, require_checkout
from tools.native_chain.models import (
    CapturedInputFile,
    NativeChainCapture,
    NativeChainDeclaration,
    NativeChainRefusal,
    NativeChainReviewRequest,
)
from tools.setup_review.composition_check import check_task
from tools.setup_review.composition_models import TaskCheckRequest
from tools.setup_review.environment_models import EnvironmentPreviewRequest
from tools.setup_review.environment_settings import inspect_environment
from tools.setup_review.models import SetupReviewRequest
from workflows.reviewed_launch_binding import verify_binding


def read_bytes(path: Path, limit: int) -> bytes:
    with open_identity_file(str(path), require_no_follow=True) as handle:
        before = regular_file_snapshot(handle)
        if before.size > limit:
            raise NativeChainRefusal("input_too_large")
        content = handle.read(limit + 1)
        if len(content) > limit:
            raise NativeChainRefusal("input_too_large")
        if regular_file_snapshot(handle) != before or not path_matches_snapshot(str(path), before):
            raise NativeChainRefusal("input_changed")
    return content


def require_cwd(declaration: NativeChainDeclaration) -> None:
    root = require_checkout(checkout_root())
    if Path.cwd() != root or declaration.working_directory != root:
        raise NativeChainRefusal("working_directory_changed")


def export_argv(declaration: NativeChainDeclaration, iteration: int, limit: int) -> tuple[str, ...]:
    require_cwd(declaration)
    if not 1 <= iteration <= declaration.run.final_iteration:
        raise NativeChainRefusal("iteration_out_of_range")
    with tempfile.TemporaryFile() as transport:
        completed = subprocess.run(
            [
                "bash",
                str(declaration.working_directory / "scripts/launch/run_chain.sh"),
                *declaration.shell_arguments(),
                "--chain_export_fd",
                str(transport.fileno()),
                "--chain_export_iteration",
                str(iteration),
            ],
            cwd=declaration.working_directory,
            pass_fds=(transport.fileno(),),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
            check=False,
        )
        if completed.returncode:
            raise NativeChainRefusal("shell_export_refused")
        transport.seek(0)
        data = transport.read(limit + 1)
    if len(data) > limit or not data or not data.endswith(b"\0"):
        raise NativeChainRefusal("invalid_shell_transport")
    return tuple(data[:-1].decode("utf-8").split("\0"))


def _overlap(first: Path, second: Path) -> bool:
    return first.is_relative_to(second) or second.is_relative_to(first)


def review(request: NativeChainReviewRequest) -> NativeChainCapture:
    source = read_bytes(request.source, request.input_max_bytes)
    declaration = NativeChainDeclaration.model_validate_json(source)
    require_cwd(declaration)
    workspace = declaration.run.workspace
    if os.path.lexists(workspace) or not workspace.parent.is_dir():
        raise NativeChainRefusal("workspace_not_fresh")
    protected = (workspace, request.source, declaration.working_directory, *request.read_only)
    if any(_overlap(request.output, path) for path in protected):
        raise NativeChainRefusal("output_overlap")
    if os.path.lexists(request.output) or not request.output.parent.is_dir():
        raise NativeChainRefusal("output_not_fresh")
    argv = export_argv(declaration, 1, request.input_max_bytes)
    # Existing parser/normalizer owns locating data. Do not initialize a task here.
    from workflows.standard_cli import build_parser, normalize_args

    try:
        with redirect_stderr(io.StringIO()):
            args = normalize_args(build_parser().parse_args(argv))
    except SystemExit as error:
        raise NativeChainRefusal("standard_arguments_refused") from error
    data = Path(args.data_dir).resolve()
    if any(
        _overlap(workspace, path)
        for path in (data, request.source, declaration.working_directory, *request.read_only)
    ):
        raise NativeChainRefusal("workspace_overlap")
    if _overlap(request.output, data):
        raise NativeChainRefusal("output_overlap")
    request.output.mkdir(mode=0o700)
    report = check_task(
        TaskCheckRequest(
            setup=SetupReviewRequest(
                working_directory=str(declaration.working_directory), argv=list(argv)
            ),
            scratch=request.output / "task-scratch",
            output=request.output / "task-check",
            read_only=request.read_only,
            settings=request.task_check,
            resolve_task_settings=True,
        )
    )
    if report.result.outcome != "passed" or report.result.task_settings is None:
        raise NativeChainRefusal("task_check_incomplete")
    task_path = request.output / "task-check/report.json"
    environment = inspect_environment(
        EnvironmentPreviewRequest(
            report=task_path,
            expected_sha256=hashlib.sha256(
                read_bytes(task_path, request.input_max_bytes)
            ).hexdigest(),
            output=request.output / "environment",
            input_max_bytes=request.input_max_bytes,
            bind_launch=True,
            check_environment=False,
        )
    )
    binding = environment.launch_binding
    assert binding is not None
    inputs = tuple(
        CapturedInputFile(
            pin=pin,
            content_base64=base64.b64encode(
                read_bytes(Path(pin.path), request.input_max_bytes)
            ).decode(),
        )
        for pin in binding.files
    )
    capture = NativeChainCapture(
        declaration=declaration,
        source_text=source.decode(),
        source_path=request.source,
        source_sha256=hashlib.sha256(source).hexdigest(),
        declaration_sha256=hashlib.sha256(declaration.model_dump_json().encode()).hexdigest(),
        shell_argv=declaration.shell_arguments(),
        iteration_one_argv=argv,
        environment=environment,
        input_files=inputs,
    )
    verify_binding(binding)
    if read_bytes(request.source, request.input_max_bytes) != source:
        raise NativeChainRefusal("source_changed")
    payload = (capture.model_dump_json(indent=2) + "\n").encode()
    if len(payload) > request.input_max_bytes:
        raise NativeChainRefusal("capture_too_large")
    (request.output / "inputs").mkdir(mode=0o700)
    for index, item in enumerate(inputs):
        publish_bytes_write_once(
            str(request.output / "inputs" / str(index)), base64.b64decode(item.content_base64)
        )
    publish_bytes_write_once(str(request.output / "capture.json"), payload)
    return capture
