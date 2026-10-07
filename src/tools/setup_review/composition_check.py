"""Explicit bounded task checks; ordinary declaration inspection never calls this."""

from __future__ import annotations

import sys

from core.durable_io import publish_bytes_write_once
from tools.setup_review.composition_models import (
    CHILD_REQUEST_NAME,
    CompositionJob,
    CompositionResult,
    TaskCheckReport,
    TaskCheckRequest,
)
from tools.setup_review.composition_paths import validate_check_locations
from tools.setup_review.composition_render import render_task_check
from tools.setup_review.composition_transport import manifest_digest, read_composition_result
from tools.setup_review.inspection import inspect_declaration
from tools.setup_review.render import render_html
from tools.workspace_sandbox.profile import SandboxProfile, runtime_roots
from tools.workspace_sandbox.runner import ExecutionResult, run
from workflows.llm_config import WorkflowLLMConfig

_LIMITATIONS = (
    "Only trusted, explicitly selected task/provider factories were composed. Their arbitrary "
    "import-time code can compute or print anything available in the mounted source/runtime roots.",
    "No dataset loading, split validation, model construction, training, scoring, Health "
    "materialization, analysis-skill execution, LLM call or credential authentication was requested.",
    "Hardware/watchdog settings and agent-selected training values remain unresolved. No GPU "
    "devices, network access or caller environment variables were granted to this child.",
    "The sandbox bounds wall time and supported namespace/process lifecycle, not total host "
    "memory or disk usage. It is not a hostile-code or hostile-host security boundary.",
    "Identity records cover owner-selected files and captured code-package members, not every "
    "ambient import or file a factory might read. Only the selected manifest was checked before/after.",
    "This is a setup observation, not immutable provenance, per-run orphan-free attestation, "
    "LLM review, launch approval or a receipt enforced by the ordinary launch command.",
)


def _execute(
    job: CompositionJob, profile: SandboxProfile, request_path: str
) -> tuple[ExecutionResult | None, CompositionResult]:
    try:
        execution = run(
            profile,
            [
                sys.executable,
                "-m",
                "tools.setup_review.composition_child",
                "--request",
                request_path,
            ],
        )
    except Exception as error:
        return None, CompositionResult.failed(job, "sandbox", error)
    if execution.status != "completed" or execution.returncode != 0:
        return execution, CompositionResult.failed(
            job,
            "sandbox",
            RuntimeError(
                f"Sandbox {execution.status}; return code {execution.returncode}. Inspect child diagnostics and the configured timeout."
            ),
        )
    try:
        result = read_composition_result(job)
    except Exception as error:
        return execution, CompositionResult.failed(job, "transport", error)
    return execution, result


def check_task(request: TaskCheckRequest) -> TaskCheckReport:
    """Compose in a bounded child and publish new local diagnostic artifacts."""
    declaration = inspect_declaration(request.setup, request.output)
    validate_check_locations(request, declaration)
    config = WorkflowLLMConfig.model_validate(declaration.declared_llm_config)
    job = CompositionJob(
        manifest=declaration.task_manifest,
        manifest_sha256=manifest_digest(declaration.task_manifest),
        planner_strategy=config.get("tune").get("planner_strategy"),
        scratch=str(request.scratch),
        settings=request.settings,
    )
    request.scratch.mkdir(mode=0o700)
    request.output.mkdir(mode=0o700)
    request_path = request.scratch / CHILD_REQUEST_NAME
    publish_bytes_write_once(str(request_path), (job.model_dump_json() + "\n").encode())
    profile = SandboxProfile(
        workspace=request.scratch,
        read_only=(*request.read_only, request_path),
        network=False,
        devices=(),
        environment_names=(),
        timeout_seconds=request.settings.timeout_seconds,
    )
    execution, result = _execute(job, profile, str(request_path))
    try:
        if manifest_digest(job.manifest) != job.manifest_sha256:
            raise ValueError(
                "Selected manifest changed during the check; rerun with unchanged inputs"
            )
    except Exception as error:
        result = CompositionResult.failed(job, "stale_manifest", error, task=result.task)
    report = TaskCheckReport(
        declaration=declaration,
        request=request,
        job=job,
        sandbox=profile,
        runtime_read_only_roots=tuple(str(path) for path in runtime_roots()),
        execution=execution,
        result=result,
        limitations=_LIMITATIONS,
    )
    for name, payload in (
        ("report.json", report.model_dump_json(indent=2) + "\n"),
        ("settings.html", render_html(declaration)),
        ("index.html", render_task_check(report)),
    ):
        publish_bytes_write_once(str(request.output / name), payload.encode())
    return report
