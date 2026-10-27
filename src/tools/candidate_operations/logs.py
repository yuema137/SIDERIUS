"""Bounded byte reads from the two fixed, registered log locations."""

import os

from .files import open_file
from .models import LogChunk, LogReadRequest, OperationStoreConfig
from .store import load_record, native_directory, operation_path, validate_config


def read_operation_log(config: OperationStoreConfig, request: LogReadRequest) -> LogChunk:
    config = validate_config(config)
    request = LogReadRequest.model_validate_json(request.model_dump_json())
    record = load_record(config, request.operation_id)
    path = (
        operation_path(config, request.operation_id) / "operation.log"
        if request.kind == "operation"
        or record.submission.kind in {"native_chain", "native_chain_resume"}
        else None
    )
    if path is None:
        # A loop continuation owns its segment worker.log beside its binding.
        if record.submission.kind == "candidate_loop_resume":
            from .loop_resume import selected_control

            path = selected_control(record) / "worker.log"
        else:
            path = native_directory(record.submission) / "worker.log"
    try:
        with open_file(path, private_file=request.kind == "operation") as descriptor:
            size = os.fstat(descriptor).st_size
            truncated = request.offset > size
            offset = 0 if truncated else request.offset
            payload = os.pread(descriptor, request.max_bytes, offset)
    except FileNotFoundError:
        return LogChunk(
            operation_id=request.operation_id,
            kind=request.kind,
            offset=request.offset,
            next_offset=request.offset,
            observed_size=0,
            missing=True,
            truncated=False,
            text="",
        )
    return LogChunk(
        operation_id=request.operation_id,
        kind=request.kind,
        offset=offset,
        next_offset=offset + len(payload),
        observed_size=size,
        missing=False,
        truncated=truncated,
        text=payload.decode("utf-8", errors="replace"),
    )
