"""Fresh envelope ownership, offline preparation and receipt-last publication."""

import hashlib
import os
import stat
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import TypeAdapter

from core.control_json import encode_control
from core.durable_io import publish_bytes_write_once
from tools.workflow_preview import WorkflowPreview

from .admission import absent_destination, admit, canonical
from .launch import publish, supervise
from .layout import proposal_receipt_path
from .models import CandidatePreparationReceipt
from .reusable_admission import capture, safe_bytes, verify_origin
from .reusable_models import (
    ReusableCandidatePreparationRequest,
    ReusablePreparationControl,
    ReusablePreparationObservations,
    ReusablePreparationReceipt,
)
from .reusable_verify import encoded, verify_reusable_bundle


def check_claim(path: Path, claimed: os.stat_result) -> None:
    """Refuse publication into a replaced directory, including a normal directory."""
    canonical(str(path))
    current = path.lstat()
    if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (
        claimed.st_dev,
        claimed.st_ino,
    ):
        raise ValueError("claimed preparation directory was replaced")


def prepare_reusable_candidate(
    request: ReusableCandidatePreparationRequest,
    *,
    invocation_id: UUID | None = None,
    expected_observations: ReusablePreparationObservations | None = None,
) -> ReusablePreparationReceipt:
    """Prepare one fresh managed-only v2 capture; never launch or resume a worker."""
    preparation_id = (
        uuid4()
        if invocation_id is None
        else TypeAdapter(UUID).validate_python(invocation_id, strict=True)
    )
    captured = capture(request)
    plan, source, captures = captured.plan, captured.source, captured.inputs
    binding = plan.binding
    if expected_observations is not None and (
        ReusablePreparationObservations.from_binding(binding) != expected_observations
    ):
        raise ValueError("actual reusable capture differs from admitted observations")
    envelope = Path(binding.envelope)
    output = Path(binding.request.output_dir)
    control_dir = output / "preparation"
    binding_path = envelope / "binding.json"
    binding_hash = hashlib.sha256(encoded(binding)).hexdigest()
    control = ReusablePreparationControl(
        preparation_id=preparation_id,
        request=binding.request,
        sources=binding.sources,
        binding_path=str(binding_path),
        binding_sha256=binding_hash,
    )
    initial = ReusablePreparationReceipt(
        preparation_id=control.preparation_id,
        run_id=binding.run_id,
        envelope=str(envelope),
        status="failed",
        binding_path=str(binding_path),
        binding_sha256=binding_hash,
    )
    native = CandidatePreparationReceipt(
        preparation_id=control.preparation_id,
        status="failed",
        output_dir=str(output),
        request_path=str(control_dir / "request.json"),
        log_path=str(control_dir / "worker.log"),
        source_observations=control.sources,
    )
    if plan.document.execution_profile is not None:
        encode_control(binding)
        encode_control(control)
    verify_origin(binding)
    envelope.mkdir()  # A losing caller must not write even a failure receipt.
    claimed = envelope.lstat()
    control_claim = None
    try:
        check_claim(envelope, claimed)
        if next(envelope.iterdir(), None) is not None:
            raise ValueError("envelope changed before exclusive claim")
        publish(binding_path, binding)
        publish_bytes_write_once(binding.snapshot_path, source)
        admit(binding.request)
        output.mkdir()
        control_dir.mkdir()
        control_claim = control_dir.lstat()
        publish(control_dir / "request.json", control)
        for name, (_, payload) in zip(("manifest.snapshot", "llm.snapshot"), captures, strict=True):
            publish_bytes_write_once(str(control_dir / name), payload)
        result = supervise(
            binding.request,
            "tools.candidate_prepare.reusable_child",
            extra_read_only=(binding_path, Path(binding.snapshot_path)),
        )
        check_claim(envelope, claimed)
        check_claim(control_dir, control_claim)
        if result.status != "completed":
            native = native.model_copy(
                update={
                    "status": result.status,
                    "error": f"preparation child exit {result.returncode}; inspect worker.log",
                }
            )
        else:
            candidate, bindings, fingerprint = verify_reusable_bundle(plan, source, control)
            verify_origin(binding)
            absent_destination(canonical(binding.request.candidate_workspace))
            preview = WorkflowPreview(**bindings.model_dump(), workspace_state="absent")
            if plan.document.execution_profile is not None:
                for record in (candidate.preview, preview, candidate):
                    encode_control(record)
            for name, record in (
                ("preview_request.json", candidate.preview),
                ("preview.json", preview),
                ("candidate_request.json", candidate),
            ):
                publish(output / name, record)
            # Recheck all selected bytes after publication. Partial files on failure
            # remain diagnostic; only the terminal top-level receipt selects success.
            checked, _, _ = verify_reusable_bundle(plan, source, control)
            if (
                checked != candidate
                or safe_bytes(output / "candidate_request.json") != encoded(candidate)
                or safe_bytes(output / "preview.json") != encoded(preview)
            ):
                raise ValueError("published request or preview changed")
            verify_origin(binding)
            absent_destination(canonical(binding.request.candidate_workspace))
            native = native.model_copy(
                update={
                    "status": "prepared",
                    "candidate_request_path": str(output / "candidate_request.json"),
                    "preview_path": str(output / "preview.json"),
                    "interpretation_path": str(output / "interpretation.json"),
                    "proposal_path": proposal_receipt_path(plan.document, output),
                    "composition_fingerprint": fingerprint,
                }
            )
            initial = initial.model_copy(
                update={
                    "candidate_request_path": native.candidate_request_path,
                    "candidate_request_sha256": hashlib.sha256(encoded(candidate)).hexdigest(),
                    "preview_sha256": hashlib.sha256(encoded(preview)).hexdigest(),
                }
            )
    except KeyboardInterrupt:
        native = native.model_copy(
            update={"status": "interrupted", "error": "preparation interrupted"}
        )
    except Exception as error:
        native = native.model_copy(
            update={"status": "failed", "error": f"{type(error).__name__}: {error}"}
        )
    check_claim(envelope, claimed)
    receipt_path = None
    if control_claim is not None:
        check_claim(control_dir, control_claim)
        publish(control_dir / "receipt.json", native)
        receipt_path = str(control_dir / "receipt.json")
    terminal = initial.model_copy(
        update={
            "status": native.status,
            "error": native.error,
            "preparation_receipt_path": receipt_path,
        }
    )
    publish(envelope / "receipt.json", terminal)
    return terminal
