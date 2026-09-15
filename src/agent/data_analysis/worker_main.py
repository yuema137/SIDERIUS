"""Isolated worker for parameter validation and selected skill execution."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from agent.schemas.data_analysis.common import canonical_json_bytes
from agent.schemas.data_analysis.skills import SkillPayload
from core.durable_io import publish_bytes_write_once

from .loader import load_selected_skill
from .skill_runtime import SkillRuntime
from .worker_protocol import SkillWorkerRequest, SkillWorkerResponse, ValidatedParameters


def _validate_materializations(request: SkillWorkerRequest) -> None:
    assert request.skill_input is not None
    views = {view.binding_id: view for view in request.skill_input.materializations}
    if set(views) != set(request.materialization_paths):
        raise ValueError("resolved materialization paths do not exactly match SkillInput")
    for binding_id, view in views.items():
        path = Path(request.materialization_paths[binding_id])
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"binding {binding_id!r} materialization is not a regular file")
        payload = path.read_bytes()
        if view.content_ref.byte_size is not None and len(payload) != view.content_ref.byte_size:
            raise ValueError(f"binding {binding_id!r} materialization byte size mismatch")
        if hashlib.sha256(payload).hexdigest() != view.content_ref.sha256:
            raise ValueError(f"binding {binding_id!r} materialization digest mismatch")


def run_worker(request: SkillWorkerRequest) -> SkillWorkerResponse:
    loaded = load_selected_skill(request.discovered_skill)
    if request.mode == "resolve_interface":
        return SkillWorkerResponse(
            status="interface_resolved",
            resolved_interface=loaded.resolved_interface(),
            environment_lock_verified=loaded.environment_lock_verified,
        )
    parameters = loaded.validate_parameters(request.parameters)
    validated = ValidatedParameters(
        parameters=parameters.model_dump(mode="json"),
        parameter_schema_sha256=loaded.parameter_schema_sha256,
        validated_parameters_sha256=loaded.validated_parameters_sha256(parameters),
    )
    if request.mode == "validate_parameters":
        if validated.parameter_schema_sha256 != request.expected_parameter_schema_sha256:
            raise ValueError("parameter schema changed after selected interface resolution")
        return SkillWorkerResponse(
            status="validated",
            validated_parameters=validated,
            environment_lock_verified=loaded.environment_lock_verified,
        )

    assert request.skill_input is not None
    assert request.artifact_directory is not None
    if validated.parameter_schema_sha256 != request.expected_parameter_schema_sha256:
        raise ValueError("parameter schema changed between validation and execution")
    if validated.validated_parameters_sha256 != request.expected_validated_parameters_sha256:
        raise ValueError("validated parameters changed between validation and execution")
    _validate_materializations(request)
    runtime = SkillRuntime(
        materialization_paths=request.materialization_paths,
        materializations=request.skill_input.materializations,
        artifact_directory=request.artifact_directory,
    )
    result = loaded.run(request.skill_input, parameters, runtime)
    payload = result if isinstance(result, SkillPayload) else SkillPayload.model_validate(result)
    return SkillWorkerResponse(
        status="completed",
        payload=payload,
        environment_lock_verified=loaded.environment_lock_verified,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--response", required=True)
    args = parser.parse_args()
    response_path = Path(args.response)
    try:
        request = SkillWorkerRequest.model_validate_json(Path(args.request).read_bytes())
        response = run_worker(request)
    except Exception as exc:
        response = SkillWorkerResponse(
            status="failed",
            error_type=type(exc).__name__,
            error_message=str(exc) or type(exc).__name__,
        )
    publish_bytes_write_once(str(response_path), canonical_json_bytes(response))
    return 0 if response.status != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
