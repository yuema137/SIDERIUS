"""Claim a fresh workspace and delegate supervision to workspace_sandbox."""

import sys
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import TypeAdapter

from core.durable_io import publish_bytes_write_once
from execute_tools.impl_attempts import impl_attempt_dir
from tools.workflow_preview import preview_workflow
from tools.workflow_preview.files import observe_file
from tools.workspace_sandbox.profile import SandboxProfile, runtime_roots
from tools.workspace_sandbox.runner import ExecutionResult, run

from .layout import candidate_proposal_dir
from .models import CandidateRunReceipt, CandidateRunRequest


def publish(path: Path, value: CandidateRunRequest | CandidateRunReceipt) -> None:
    publish_bytes_write_once(str(path), (value.model_dump_json(indent=2) + "\n").encode())


def reconcile(
    initial: CandidateRunReceipt, result: ExecutionResult, child_path: Path
) -> CandidateRunReceipt:
    """A child result never overrides timeout or failed process completion."""
    if result.status != "completed":
        return initial.model_copy(
            update={"status": result.status, "error": f"worker exit {result.returncode}"}
        )
    try:
        child = CandidateRunReceipt.model_validate_json(child_path.read_bytes())
        for name in (
            "run_id",
            "run_name",
            "workspace",
            "declaration_digest",
            "node_ids",
            "selected_constructor_routes",
            "ledger_path",
            "log_path",
        ):
            if getattr(child, name) != getattr(initial, name):
                raise ValueError(f"child receipt changed {name}")
        if child.status not in {"accepted", "rejected"}:
            raise ValueError("child did not report terminal candidate validation")
        if (
            child.validation_passed != (child.status == "accepted")
            or len(child.native_output_paths) != 3
        ):
            raise ValueError("inconsistent native validation receipt")
        proposal_dir = candidate_proposal_dir(Path(initial.workspace), initial.run_name)
        implementation_dir = Path(impl_attempt_dir(str(proposal_dir), 1))
        expected_paths = (
            str(proposal_dir / f"proposal_{initial.run_name}.json"),
            str(implementation_dir / f"implementor_{initial.run_name}.json"),
            str(implementation_dir / f"validation_{initial.run_name}.json"),
        )
        if (
            child.proposal_storage != str(proposal_dir)
            or child.implementation_storage != str(implementation_dir)
            or child.native_output_paths != expected_paths
            or not child.candidate_id
            or not child.composition_fingerprint
            or not all(Path(path).is_file() for path in expected_paths)
        ):
            raise ValueError("child receipt lacks the managed native output records")
        return child
    except (OSError, ValueError) as error:
        return initial.model_copy(update={"status": "failed", "error": str(error)})


def launch_candidate(
    request: CandidateRunRequest, *, invocation_id: UUID | None = None
) -> CandidateRunReceipt:
    """Run precisely one chain; failures preserve the claimed workspace."""
    request = CandidateRunRequest.model_validate_json(request.model_dump_json())
    identity = (
        uuid4()
        if invocation_id is None
        else TypeAdapter(UUID).validate_python(invocation_id, strict=True)
    )
    observed = preview_workflow(request.preview)
    definition = request.preview.document.definition
    if request.declaration_digest != definition.declaration_digest():
        raise ValueError("stale workflow declaration")
    if (
        request.files != observed.files
        or request.selected_constructor_routes != observed.selected_constructor_routes
    ):
        raise ValueError("stale selected files or constructor routes")
    captures = []
    for expected in observed.files:
        actual, payload = observe_file(Path(expected.path), expected.reference)
        if actual != expected:
            raise ValueError(f"selected input changed: {expected.reference}")
        captures.append(payload)
    workspace = Path(observed.workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    # mkdir is the exclusive ownership claim. Losing callers never publish files.
    control = workspace / "candidate_run"
    control.mkdir()
    initial = CandidateRunReceipt(
        run_id=identity.hex,
        run_name=request.run_name,
        workspace=str(workspace),
        declaration_digest=request.declaration_digest,
        status="launched",
        node_ids=tuple(node.id for node in definition.nodes),
        selected_constructor_routes=observed.selected_constructor_routes,
        ledger_path=str(workspace / "token_usage.jsonl"),
        log_path=str(control / "worker.log"),
    )
    publish(control / "launch.json", initial)
    try:
        if any(path != control for path in workspace.iterdir()):
            raise ValueError("workspace became nonempty before exclusive claim")
        publish(control / "request.json", request)
        for index, payload in enumerate(captures):
            publish_bytes_write_once(str(control / f"input_{index:03}.snapshot"), payload)
        profile = SandboxProfile(
            workspace=workspace,
            read_only=tuple(Path(p) for p in request.read_only),
            network=request.network,
            devices=tuple(Path(p) for p in request.devices),
            environment_names=request.environment_names,
            timeout_seconds=request.timeout_seconds,
        )
        roots = (*profile.read_only, *runtime_roots())
        for path in (Path(observed.data_root), *(Path(item.path) for item in observed.files)):
            if not any(path.is_relative_to(root) for root in roots):
                raise ValueError(f"selected input needs an explicit read-only mount: {path}")
        result = run(
            profile,
            [sys.executable, "-m", "tools.candidate_worker.child", str(control / "request.json")],
        )
        terminal = reconcile(initial, result, control / "child.json")
    except KeyboardInterrupt:
        terminal = initial.model_copy(
            update={"status": "interrupted", "error": "worker interrupted"}
        )
    except Exception as error:
        terminal = initial.model_copy(
            update={"status": "failed", "error": f"{type(error).__name__}: {error}"}
        )
    publish(control / "receipt.json", terminal)
    return terminal
