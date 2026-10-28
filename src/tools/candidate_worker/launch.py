"""Claim a fresh workspace and delegate supervision to workspace_sandbox."""

import os
import sys
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import TypeAdapter

from core.control_json import encode_control
from core.durable_io import publish_bytes_write_once
from core.seeding import RunSeedBinding, admitted_run_seed
from execute_tools.impl_attempts import impl_attempt_dir
from tools.workflow_preview.files import observe_file
from tools.workspace_sandbox.profile import SandboxProfile
from tools.workspace_sandbox.runner import (
    CancelProbe,
    ExecutionResult,
    SpawnObserver,
    SupervisionOptions,
    run,
    run_observed,
)

from .admission import admit_input_paths
from .layout import candidate_proposal_dir
from .models import RECEIPT_IDENTITY_FIELDS, CandidateRunReceipt, CandidateRunRequest
from .preflight import fresh_preview, require_credentials


def publish(
    path: Path, value: CandidateRunRequest | CandidateRunReceipt, *, bounded: bool = False
) -> None:
    payload = (
        encode_control(value) if bounded else (value.model_dump_json(indent=2) + "\n").encode()
    )
    publish_bytes_write_once(str(path), payload)


def reconcile(
    initial: CandidateRunReceipt,
    result: ExecutionResult,
    child_path: Path,
    *,
    training: bool = False,
    graph_request: CandidateRunRequest | None = None,
) -> CandidateRunReceipt:
    """A child result never overrides timeout or failed process completion."""
    if result.status != "completed":
        return initial.model_copy(
            update={"status": result.status, "error": f"worker exit {result.returncode}"}
        )
    try:
        from .graph_evidence import read_graph_control, verify_graph_trace

        child = CandidateRunReceipt.model_validate_json(
            read_graph_control(child_path) if graph_request is not None else child_path.read_bytes()
        )
        if child.status == "cancelled":
            raise ValueError("only supervision records cancellation")
        for name in RECEIPT_IDENTITY_FIELDS:
            if getattr(child, name) != getattr(initial, name):
                raise ValueError(f"child receipt changed {name}")
        if graph_request is not None:
            if graph_request.preview.document.definition.loop is not None:
                from .loop_evidence import verify_loop

                verify_loop(graph_request, initial, child)
            else:
                verify_graph_trace(graph_request, initial, child)
            return child
        if child.graph_trace is not None or child.loop_trace is not None:
            raise ValueError("fixed candidate receipt cannot contain graph evidence")
        has_training_output = training and child.status in {"completed", "failed"}
        allowed = {"rejected", "completed", "failed"} if training else {"accepted", "rejected"}
        if child.status not in allowed:
            raise ValueError("child did not report terminal candidate validation")
        if child.validation_passed != (child.status != "rejected") or len(
            child.native_output_paths
        ) != (4 if has_training_output else 3):
            raise ValueError("inconsistent native validation receipt")
        if has_training_output:
            from .training_evidence import verify_training_evidence

            verify_training_evidence(child)
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
            or child.native_output_paths[:3] != expected_paths
            or not child.candidate_id
            or not child.composition_fingerprint
            or not all(Path(path).is_file() for path in expected_paths)
        ):
            raise ValueError("child receipt lacks the managed native output records")
        return child
    except (OSError, ValueError) as error:
        return initial.model_copy(update={"status": "failed", "error": str(error)})


def launch_candidate(
    request: CandidateRunRequest,
    *,
    invocation_id: UUID | None = None,
    run_seed: RunSeedBinding | None = None,
    on_sandbox_spawn: SpawnObserver | None = None,
    cancel_requested: CancelProbe | None = None,
) -> CandidateRunReceipt:
    """Run precisely one chain; failures preserve the claimed workspace.

    ``run_seed`` is the seed an operation admission already bound (issue #983);
    a direct call omits it and this entry boundary binds ``request.run_seed`` or
    generates one. Either way the initial receipt records it before any node runs.
    ``on_sandbox_spawn`` receives the sandbox PID before the chain is awaited (the
    host reservation ledger binds it); omitted, the launch is unchanged.
    ``cancel_requested`` is polled while the sandbox runs; when it fires the
    sandbox group is terminated and the receipt status is ``cancelled``.
    """
    request = CandidateRunRequest.model_validate_json(request.model_dump_json())
    seed = admitted_run_seed(request.run_seed, run_seed)
    identity = (
        uuid4()
        if invocation_id is None
        else TypeAdapter(UUID).validate_python(invocation_id, strict=True)
    )
    observed = fresh_preview(request)
    definition = request.preview.document.definition
    require_credentials(observed.selected_constructor_routes, request.environment_names, os.environ)
    captures = []
    for expected in observed.files:
        actual, payload = observe_file(Path(expected.path), expected.reference)
        if actual != expected:
            raise ValueError(f"selected input changed: {expected.reference}")
        captures.append(payload)
    workspace = Path(observed.workspace)
    control = workspace / "candidate_run"
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
        run_seed=seed.value,
        run_seed_source=seed.source,
    )
    graph = request.preview.execution_profile is not None
    if graph:
        from .graph_evidence import admit_graph_control

        admit_graph_control(request, initial)
    workspace.mkdir(parents=True, exist_ok=True)
    # mkdir is the exclusive ownership claim. Losing callers never publish files.
    control.mkdir()
    publish(control / "launch.json", initial, bounded=graph)
    try:
        if any(path != control for path in workspace.iterdir()):
            raise ValueError("workspace became nonempty before exclusive claim")
        publish(control / "request.json", request, bounded=graph)
        if request.workflow_source is not None:
            publish_bytes_write_once(
                str(control / "workflow.py.snapshot"),
                request.workflow_source.source.encode("utf-8"),
            )
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
        admit_input_paths(
            (Path(observed.data_root), *(Path(item.path) for item in observed.files)),
            request.read_only,
        )
        argv = [sys.executable, "-m", "tools.candidate_worker.child", str(control / "request.json")]
        observer: SupervisionOptions = {}
        if on_sandbox_spawn is not None:
            observer["on_spawn"] = on_sandbox_spawn
        if cancel_requested is not None:
            observer["cancel_requested"] = cancel_requested
        if definition.loop is not None:
            observed_result = run_observed(profile, argv, **observer)
            publish_bytes_write_once(
                str(control / "supervision.json"), encode_control(observed_result)
            )
            result = observed_result.execution
        else:
            result = run(profile, argv, **observer)
        terminal = reconcile(
            initial,
            result,
            control / "child.json",
            training=any(node.capability == "tuning" for node in definition.nodes),
            graph_request=request if graph else None,
        )
        if terminal.status == "paused":
            from .loop_resume import require_clean

            require_clean(control)
    except KeyboardInterrupt:
        terminal = initial.model_copy(
            update={"status": "interrupted", "error": "worker interrupted"}
        )
    except Exception as error:
        terminal = initial.model_copy(
            update={"status": "failed", "error": f"{type(error).__name__}: {error}"}
        )
    if graph:
        terminal = bounded_terminal(initial, terminal)
    publish(control / "receipt.json", terminal, bounded=graph)
    return terminal


def bounded_terminal(
    initial: CandidateRunReceipt, terminal: CandidateRunReceipt
) -> CandidateRunReceipt:
    try:
        encode_control(terminal)
        return terminal
    except ValueError:
        failure = initial.model_copy(update={"status": "failed", "error": "graph_control_overflow"})
        encode_control(failure)
        return failure
