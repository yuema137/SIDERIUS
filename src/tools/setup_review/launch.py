"""Optional reviewed standard launch; direct standard execution remains available."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from tools.setup_review.environment_models import EnvironmentPreviewReport
from tools.setup_review.launch_models import ReviewedLaunchRequest
from tools.setup_review.semantic_models import SemanticReviewReceipt, SnapshotInputError
from tools.setup_review.semantic_packet import build_packet, packet_text
from tools.setup_review.snapshot_io import (
    claim_snapshot_output,
    read_snapshot,
    read_verified_json,
)
from workflows.reviewed_launch import ReviewedLaunchContext
from workflows.reviewed_launch_binding import ReviewedLaunchRefusal


def _finding_digest(finding) -> str:
    return hashlib.sha256(finding.model_dump_json().encode()).hexdigest()


def prepare_reviewed_launch(
    request: ReviewedLaunchRequest,
) -> tuple[ReviewedLaunchContext, list[str]]:
    """Read bounded artifacts, match the exact review and validate user dispositions."""
    report = read_snapshot(request)
    if not isinstance(report, EnvironmentPreviewReport) or report.launch_binding is None:
        raise SnapshotInputError(
            "Reviewed launch requires an environment report made with --bind-launch"
        )
    receipt = SemanticReviewReceipt.model_validate(
        read_verified_json(request.receipt, request.receipt_sha256, request.input_max_bytes)
    )
    if (
        receipt.source_sha256 != request.expected_sha256
        or receipt.source_schema != report.schema_version
        or receipt.prompt_version != "setup-review/v3"
        or receipt.packet_sha256
        != hashlib.sha256(packet_text(build_packet(report)).encode()).hexdigest()
    ):
        raise SnapshotInputError("Review receipt does not bind this environment packet")
    result = report.saved_task_check.result
    if (
        receipt.outcome == "failed"
        or result.outcome != "passed"
        or result.task is None
        or result.task_settings is None
        or result.planner_strategy_identity is None
    ):
        raise SnapshotInputError("Failed or incomplete deterministic/review evidence cannot launch")
    findings = receipt.judgement.findings if receipt.judgement is not None else []
    seen: set[int] = set()
    for item in request.dispositions:
        if (
            item.index in seen
            or item.index >= len(findings)
            or not item.reason.strip()
            or item.finding_sha256 != _finding_digest(findings[item.index])
        ):
            raise SnapshotInputError("Finding disposition does not match this receipt")
        seen.add(item.index)
    required = {
        index for index, finding in enumerate(findings) if finding.severity != "information"
    }
    if not required.issubset(seen):
        raise SnapshotInputError(
            "Every error/warning finding needs a matching acknowledgement and reason"
        )
    from tools.setup_review.inspection import inspect_parsed_declaration

    current, _ = inspect_parsed_declaration(report.current_declaration.request, request.output)
    excluded = {"output_directory", "environment_check_requested", "credentials"}
    if current.model_dump(exclude=excluded) != report.current_declaration.model_dump(
        exclude=excluded
    ):
        raise SnapshotInputError(
            "Current declaration differs; regenerate the task/environment review"
        )
    receipt_path = request.receipt.absolute()
    if request.output == receipt_path or request.output in receipt_path.parents:
        raise SnapshotInputError("Output must be separate from the review receipt")
    claim_snapshot_output(request, report)
    from workflows.reviewed_launch_binding import stable_hardware

    context = ReviewedLaunchContext(
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
        receipt_path=str(request.output / "launch-check.json"),
        receipt_fields={
            "schema_version": "siderius.reviewed-launch/v1",
            "environment_sha256": request.expected_sha256,
            "review_sha256": request.receipt_sha256,
            "request_sha256": hashlib.sha256(request.model_dump_json().encode()).hexdigest(),
            "dispositions": [item.model_dump(mode="json") for item in request.dispositions],
            "review_outcome": receipt.outcome,
            "skip_reason": receipt.skip_reason,
            "finding_count": len(findings),
            "limitations": [
                "Matching launch inputs do not establish successful execution or authenticate credentials.",
                "Arbitrary task runtime and concurrent same-user changes are not certified.",
            ],
        },
    )
    return context, report.current_declaration.request.argv


def launch_reviewed(request: ReviewedLaunchRequest):
    context, argv = prepare_reviewed_launch(request)
    return _launch_prepared(context, argv)


def _launch_prepared(context: ReviewedLaunchContext, argv: list[str]):
    try:
        from workflows.reviewed_launch_binding import verify_binding

        if Path.cwd() != Path(context.working_directory):
            raise ReviewedLaunchRefusal("working_directory_changed")
        verify_binding(context.binding)
        # Only this explicitly selected operation imports the ordinary effectful runner.
        from workflows.run_one_iteration import main as standard_main

        return standard_main(argv, reviewed_setup=context)
    except BaseException as error:
        if not Path(context.receipt_path).exists():
            reason = (
                str(error) if isinstance(error, ReviewedLaunchRefusal) else "native_launch_refused"
            )
            context.publish("refused", reason)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        request = ReviewedLaunchRequest.model_validate_json(args.request.read_bytes())
        context, launch_argv = prepare_reviewed_launch(request)
    except (SnapshotInputError, ReviewedLaunchRefusal) as error:
        print(
            f"Reviewed launch refused: {error}. Correct the request or regenerate changed reports."
        )
        return 2
    except (OSError, ValueError, RuntimeError):
        print(
            "Reviewed launch refused: request or artifact validation failed. Check --request, "
            "report/receipt paths, permissions, SHA-256 values and input byte limit. "
            "No reviewed launch was authorized. Supplied values are omitted."
        )
        return 2
    # Native execution errors retain the ordinary runner's exception and cause;
    # the matched receipt may already have authorized workflow execution.
    try:
        _launch_prepared(context, launch_argv)
    except ReviewedLaunchRefusal as error:
        print(
            f"Reviewed launch refused: {error}. Correct the request or regenerate changed reports."
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
