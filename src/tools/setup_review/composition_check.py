"""Explicit bounded task checks; ordinary declaration inspection never calls this."""

from __future__ import annotations

import sys
from pathlib import Path

from core.durable_io import publish_bytes_write_once
from tools.setup_review.composition_models import (
    CHILD_REQUEST_NAME,
    CompositionJob,
    CompositionObservation,
    CompositionResult,
    TaskCheckReport,
    TaskCheckRequest,
)
from tools.setup_review.composition_paths import (
    validate_check_locations,
    validate_observation_locations,
)
from tools.setup_review.composition_render import render_task_check
from tools.setup_review.composition_transport import manifest_digest, read_composition_result
from tools.setup_review.inspection import inspect_parsed_declaration
from tools.setup_review.render import render_html
from tools.setup_review.task_settings_inputs import project_task_settings
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


def _limitations(resolve_settings: bool) -> tuple[str, ...]:
    if not resolve_settings:
        return _LIMITATIONS
    return (
        _LIMITATIONS[0],
        "Task-dependent scope, formal-launch policy, analysis routing and Health configuration "
        "resolution were requested. Consult the result for completion or failure; no actual "
        "Health evaluations, dataset loading, training or LLM call was requested.",
        *_LIMITATIONS[2:],
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


def observe_composition(
    job: CompositionJob, read_only: tuple[Path, ...], *, data_root: Path | None = None
) -> CompositionObservation:
    """Run the existing inspection child; callers supply trusted explicit source roots."""
    job = CompositionJob.model_validate_json(job.model_dump_json())
    scratch = Path(job.scratch)
    validate_observation_locations(scratch, read_only, Path(job.manifest), data_root)
    scratch.mkdir(mode=0o700)
    request_path = scratch / CHILD_REQUEST_NAME
    publish_bytes_write_once(str(request_path), (job.model_dump_json() + "\n").encode())
    profile = SandboxProfile(
        workspace=scratch,
        read_only=(*read_only, request_path),
        network=False,
        devices=(),
        environment_names=(),
        timeout_seconds=job.settings.timeout_seconds,
    )
    execution, result = _execute(job, profile, str(request_path))
    try:
        if manifest_digest(job.manifest) != job.manifest_sha256:
            raise ValueError(
                "Selected manifest changed during the check; rerun with unchanged inputs"
            )
    except Exception as error:
        result = CompositionResult.failed(job, "stale_manifest", error, task=result.task)
    return CompositionObservation(
        job=job,
        sandbox=profile,
        execution=execution,
        result=result,
        limitations=_limitations(job.task_settings is not None),
    )


def check_task(request: TaskCheckRequest) -> TaskCheckReport:
    """Compose in a bounded child and publish new local diagnostic artifacts."""
    declaration, args = inspect_parsed_declaration(request.setup, request.output)
    validate_check_locations(request, declaration)
    config = WorkflowLLMConfig.model_validate(declaration.declared_llm_config)
    job = CompositionJob(
        manifest=declaration.task_manifest,
        manifest_sha256=manifest_digest(declaration.task_manifest),
        planner_strategy=config.get("tune").get("planner_strategy"),
        scratch=str(request.scratch),
        settings=request.settings,
        task_settings=project_task_settings(args, declaration, config)
        if request.resolve_task_settings
        else None,
    )
    request.output.mkdir(mode=0o700)
    observed = observe_composition(job, request.read_only)
    report = TaskCheckReport(
        declaration=declaration,
        request=request,
        job=job,
        sandbox=observed.sandbox,
        runtime_read_only_roots=tuple(str(path) for path in runtime_roots()),
        execution=observed.execution,
        result=observed.result,
        limitations=observed.limitations,
    )
    for name, payload in (
        ("report.json", report.model_dump_json(indent=2) + "\n"),
        ("settings.html", render_html(declaration)),
        ("index.html", render_task_check(report)),
    ):
        publish_bytes_write_once(str(request.output / name), payload.encode())
    return report
