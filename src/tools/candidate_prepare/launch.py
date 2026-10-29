"""Admission, offline supervision and publication; no native task imports."""

import sys
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, TypeAdapter

from core.durable_io import publish_bytes_write_once
from core.seeding import RunSeedBinding, admitted_run_seed
from tools.workflow_preview import WorkflowPreview
from tools.workspace_sandbox.profile import SandboxProfile
from tools.workspace_sandbox.runner import ExecutionResult, run

from .admission import absent_destination, admit, canonical, verify_sources
from .bundle import verify_bundle
from .models import (
    CandidatePreparationReceipt,
    CandidatePreparationRequest,
    PreparationControl,
)


def publish(path: Path, model: BaseModel) -> None:
    publish_bytes_write_once(str(path), (model.model_dump_json(indent=2) + "\n").encode())


def reconcile(
    control: PreparationControl, initial: CandidatePreparationReceipt
) -> CandidatePreparationReceipt:
    """Accept only the fixed artifact set bound to this control and native declaration."""
    request = control.request
    output = canonical(request.output_dir)
    canonical(str(output / "preparation"))
    verify_sources(control)
    absent_destination(canonical(request.candidate_workspace))
    candidate, bindings, fingerprint = verify_bundle(control)
    preview_request = candidate.preview
    preview = WorkflowPreview(**bindings.model_dump(), workspace_state="absent")
    for name, record in (
        ("preview_request.json", preview_request),
        ("preview.json", preview),
        ("candidate_request.json", candidate),
    ):
        publish(output / name, record)
    verify_sources(control)
    absent_destination(canonical(request.candidate_workspace))
    return initial.model_copy(
        update={
            "status": "prepared",
            "composition_fingerprint": fingerprint,
            "candidate_request_path": str(output / "candidate_request.json"),
            "preview_path": str(output / "preview.json"),
            "interpretation_path": str(output / "interpretation.json"),
            "proposal_path": str(output / "proposal.json"),
        }
    )


def prepare_candidate(
    request: CandidatePreparationRequest,
    *,
    invocation_id: UUID | None = None,
    run_seed: RunSeedBinding | None = None,
) -> CandidatePreparationReceipt:
    """Prepare one fresh bundle; preserve partial files on failure and never launch it.

    ``run_seed`` is the seed an operation admission bound (issue #983); a direct
    call omits it and this entry boundary binds ``request.run_seed`` or generates.
    """
    request = CandidatePreparationRequest.model_validate_json(request.model_dump_json())
    seed = admitted_run_seed(request.run_seed, run_seed)
    identity = (
        uuid4()
        if invocation_id is None
        else TypeAdapter(UUID).validate_python(invocation_id, strict=True)
    )
    captures = admit(request)
    output = Path(request.output_dir)
    control_dir = output / "preparation"
    control = PreparationControl(
        preparation_id=identity, request=request, sources=tuple(item for item, _ in captures)
    )
    initial = CandidatePreparationReceipt(
        preparation_id=control.preparation_id,
        status="failed",
        output_dir=str(output),
        request_path=str(control_dir / "request.json"),
        log_path=str(control_dir / "worker.log"),
        source_observations=control.sources,
        run_seed=seed.value,
        run_seed_source=seed.source,
    )
    output.mkdir()  # The losing caller must not publish any record.
    try:
        if canonical(str(output)) != output or next(output.iterdir(), None) is not None:
            raise ValueError("output directory changed before exclusive claim")
        absent_destination(canonical(request.candidate_workspace))
        verify_sources(control)
        control_dir.mkdir()
        publish(control_dir / "request.json", control)
        for name, (_, payload) in zip(("manifest.snapshot", "llm.snapshot"), captures, strict=True):
            publish_bytes_write_once(str(control_dir / name), payload)
        result = supervise(request, "tools.candidate_prepare.child")
        if result.status == "completed":
            terminal = reconcile(control, initial)
        else:
            terminal = initial.model_copy(
                update={
                    "status": result.status,
                    "error": f"preparation child exit {result.returncode}; inspect worker.log and declared source mounts",
                }
            )
    except KeyboardInterrupt:
        terminal = initial.model_copy(
            update={"status": "interrupted", "error": "preparation interrupted"}
        )
    except Exception as error:
        terminal = initial.model_copy(
            update={"status": "failed", "error": f"{type(error).__name__}: {error}"}
        )
    # Do not follow a replaced control directory when publishing from the parent.
    canonical(str(control_dir))
    publish(control_dir / "receipt.json", terminal)
    return terminal


def supervise(
    request: CandidatePreparationRequest,
    module: str,
    *,
    extra_read_only: tuple[Path, ...] = (),
) -> ExecutionResult:
    """One native offline sandbox policy for both declaration formats."""
    output = Path(request.output_dir)
    profile = SandboxProfile(
        workspace=output,
        read_only=tuple(
            Path(path)
            for path in sorted(
                set(
                    (
                        request.data_root,
                        request.task_manifest,
                        request.llm_config_file,
                        *request.task_read_only,
                        *(str(path) for path in extra_read_only),
                    )
                )
            )
        ),
        network=False,
        devices=(),
        environment_names=(),
        timeout_seconds=request.preparation_timeout_seconds,
    )
    return run(
        profile,
        [
            sys.executable,
            "-m",
            module,
            str(output / "preparation/request.json"),
        ],
    )
