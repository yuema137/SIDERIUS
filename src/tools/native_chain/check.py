"""Read-only capture admission and per-dispatch checks for the existing shell."""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path

from pydantic import ValidationError

from tools.native_chain.models import (
    NativeChainCapture,
    NativeChainCaptureReference,
    NativeChainDispatch,
    NativeChainRefusal,
)
from tools.native_chain.review import export_argv, read_bytes, require_cwd
from workflows.native_chain_binding import NativeChainLaunchContext
from workflows.reviewed_launch_binding import (
    InputFilePin,
    ReviewedLaunchRefusal,
    stable_hardware,
    verify_binding,
)


def load_capture(reference: NativeChainCaptureReference) -> NativeChainCapture:
    payload = read_bytes(reference.path, reference.input_max_bytes)
    if hashlib.sha256(payload).hexdigest() != reference.sha256:
        raise NativeChainRefusal("capture_digest_changed")
    capture = NativeChainCapture.model_validate_json(payload)
    require_cwd(capture.declaration)
    source = read_bytes(capture.source_path, reference.input_max_bytes)
    if hashlib.sha256(source).hexdigest() != capture.source_sha256:
        raise NativeChainRefusal("source_changed")
    binding = capture.environment.launch_binding
    assert binding is not None
    if binding.file_max_bytes != reference.input_max_bytes:
        raise NativeChainRefusal("input_limit_changed")
    verify_binding(binding)
    return capture


def admit(reference: NativeChainCaptureReference, argv: tuple[str, ...]) -> None:
    capture = load_capture(reference)
    controls = {
        "--expected_chain_capture": str(reference.path),
        "--expected_chain_capture_sha256": reference.sha256,
        "--chain_capture_input_max_bytes": str(reference.input_max_bytes),
    }
    tokens: list[str] = []
    seen: set[str] = set()
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in controls:
            if token in seen or index + 1 == len(argv) or argv[index + 1] != controls[token]:
                raise NativeChainRefusal("capture_controls_changed")
            seen.add(token)
            index += 2
        elif token == "--dry-run":
            if token in seen:
                raise NativeChainRefusal("capture_controls_changed")
            seen.add(token)
            index += 1
        else:
            tokens.append(token)
            index += 1
    if not controls.keys() <= seen or tuple(tokens) != capture.shell_argv:
        raise NativeChainRefusal("shell_arguments_changed")
    workspace = capture.declaration.run.workspace
    if os.path.lexists(workspace) or not workspace.parent.is_dir():
        raise NativeChainRefusal("workspace_not_fresh")
    if export_argv(capture.declaration, 1, reference.input_max_bytes) != capture.iteration_one_argv:
        raise NativeChainRefusal("shell_projection_changed")


def verify_dispatch(dispatch: NativeChainDispatch) -> NativeChainCapture:
    capture = load_capture(dispatch.capture)
    expected = export_argv(
        capture.declaration, dispatch.iteration, dispatch.capture.input_max_bytes
    )
    if dispatch.argv != expected:
        raise NativeChainRefusal("dispatch_arguments_changed")
    return capture


def launch_context(capture: NativeChainCapture, iteration: int) -> NativeChainLaunchContext:
    report = capture.environment
    result = report.saved_task_check.result
    assert report.launch_binding is not None
    assert result.task is not None and result.task_settings is not None
    assert result.planner_strategy_identity is not None
    return NativeChainLaunchContext(
        binding=report.launch_binding,
        working_directory=report.current_declaration.request.working_directory,
        manifest=report.current_declaration.task_manifest,
        workspace=report.current_declaration.workspace,
        manifest_sha256=result.manifest_sha256,
        composition_fingerprint=result.task.semantic_fingerprint,
        code_package_identity=result.task.code_package_identity,
        planner_identity=result.planner_strategy_identity,
        health_config_sha256=result.task_settings.health_config_sha256,
        llm_config=report.current_declaration.declared_llm_config,
        launch_identity=report.current_declaration.launch_identity,
        launch_settings=report.launch_settings,
        hardware=stable_hardware(report.gpu_runtime),
        watchdog=report.watchdog.model_dump(mode="json"),
        aggregate_ceiling=report.aggregate_gpu_ceiling.model_dump(mode="json")
        if report.aggregate_gpu_ceiling is not None
        else None,
        iteration=iteration,
        final_iteration=capture.declaration.run.final_iteration,
        run_name=capture.declaration.run.run_name,
        source_pin=InputFilePin(
            path=str(capture.source_path),
            sha256=capture.source_sha256,
            size=len(capture.source_text.encode()),
        ),
    )


def parse_check(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("admit", "dispatch"))
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--input-max-bytes", type=int, required=True)
    parser.add_argument("--iteration", type=int)
    # Split at an explicit separator; scientific options belong to their owner.
    supplied = sys.argv[1:] if argv is None else argv
    boundary = supplied.index("--")
    args = parser.parse_args(supplied[:boundary])
    reference = NativeChainCaptureReference(
        path=args.capture, sha256=args.sha256, input_max_bytes=args.input_max_bytes
    )
    return args, reference, tuple(supplied[boundary + 1 :])


def print_refusal(error: Exception) -> None:
    reason = (
        str(error)
        if isinstance(error, (NativeChainRefusal, ReviewedLaunchRefusal))
        else "capture_input_refused"
    )
    print(f"Native chain refused: {reason}", file=sys.stderr)


# Verification failures only: native execution is deliberately outside this catch.
CHECK_ERRORS = (
    NativeChainRefusal,
    ReviewedLaunchRefusal,
    ValidationError,
    OSError,
    ValueError,
    subprocess.TimeoutExpired,
    subprocess.CalledProcessError,
)


def main() -> int:
    try:
        args, reference, argv = parse_check()
        if args.command == "admit":
            admit(reference, argv)
        else:
            verify_dispatch(
                NativeChainDispatch(capture=reference, iteration=args.iteration, argv=argv)
            )
    except CHECK_ERRORS as error:
        print_refusal(error)
        return 78
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
