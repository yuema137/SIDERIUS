"""Read only fixed native records and a bounded concurrent-append ledger prefix."""

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ValidationError

from agent.schemas.telemetry.token_usage import TokenUsageRow

from .models import CandidateRunReceipt, CandidateRunRequest
from .records import verify_candidate_records
from .token_models import (
    CandidateTokenGroup,
    CandidateTokenQuality,
    CandidateTokenReadRequest,
    CandidateTokenSnapshot,
)

BYTE_LIMIT = 4 * 1024 * 1024
ROW_LIMIT = 10_000
LINE_LIMIT = 64 * 1024
GROUP_LIMIT = 256
IDENTITY_LIMIT = 256


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def canonical(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or str(path) != value or path.resolve() != path:
        raise ValueError("use canonical absolute paths without aliases")
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError("symlink components are not allowed")
    return path


@contextmanager
def open_fixed(path: Path) -> Iterator[int]:
    """Pin all directory components and refuse symlink/nonregular fixed files."""
    parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("expected a regular native record")
        yield descriptor
    finally:
        os.close(descriptor)


def read_model[Model: BaseModel](path: Path, model: type[Model]) -> Model:
    with open_fixed(path) as descriptor:
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            payload = stream.read(BYTE_LIMIT + 1)
        if len(payload) > BYTE_LIMIT:
            raise ValueError("native JSON record exceeds 4 MiB")
    return model.model_validate_json(payload)


def ledger_prefix(path: Path) -> tuple[bytes, CandidateTokenQuality]:
    with open_fixed(path) as descriptor:
        size = os.fstat(descriptor).st_size
        requested = min(size, BYTE_LIMIT)
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            payload = stream.read(requested)
        short = len(payload) < requested or os.fstat(descriptor).st_size < size
    return payload, CandidateTokenQuality(truncated_bytes=size > BYTE_LIMIT, short_read=short)


def timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(UTC) if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def aggregate(
    payload: bytes, *, run_id: str, run_name: str, quality: CandidateTokenQuality
) -> tuple[tuple[CandidateTokenGroup, ...], CandidateTokenQuality, str | None]:
    """Sum each reported field independently, without retry deduplication."""
    counters = quality.model_dump()
    groups: dict[tuple[str, str, str | None], CandidateTokenGroup] = {}
    last: datetime | None = None
    lines = payload.split(b"\n")
    counters["trailing_fragment"] = bool(lines[-1])
    complete = lines[:-1]
    counters["truncated_rows"] = len(complete) > ROW_LIMIT
    for line in complete[:ROW_LIMIT]:
        if len(line) > LINE_LIMIT:
            counters["oversized_rows"] += 1
            continue
        try:
            row = TokenUsageRow.model_validate_json(line)
        except (ValidationError, ValueError):
            counters["invalid_rows"] += 1
            continue
        counts = (row.tokens.prompt, row.tokens.completion, row.tokens.total)
        if (
            row.run_id != run_id
            or row.run_name != run_name
            or any(value is not None and value < 0 for value in counts)
        ):
            counters["invalid_rows"] += 1
            continue
        if (
            row.provider is None
            and row.model is None
            and row.served_model is None
            and all(value is None for value in counts)
        ):
            counters["marker_rows"] += 1
            continue
        if row.provider is None or row.model is None:
            counters["invalid_rows"] += 1
            continue
        key = (row.provider, row.model, row.served_model)
        if any(value is not None and len(value.encode("utf-8")) > IDENTITY_LIMIT for value in key):
            counters["excluded_identity_rows"] += 1
            continue
        if key not in groups and len(groups) >= GROUP_LIMIT:
            counters["excluded_group_rows"] += 1
            continue
        group = groups.get(
            key,
            CandidateTokenGroup(
                provider=row.provider, requested_model=row.model, served_model=row.served_model
            ),
        )
        updates: dict[str, int | None] = {"response_rows": group.response_rows + 1}
        for name, value in zip(("input", "output", "total"), counts, strict=True):
            field = f"reported_{name}_tokens"
            missing = f"missing_{name}_rows"
            updates[field] = (
                (getattr(group, field) or 0) + value if value is not None else getattr(group, field)
            )
            updates[missing] = getattr(group, missing) + (value is None)
        groups[key] = group.model_copy(update=updates)
        observed = timestamp(row.ts)
        if observed is None:
            counters["invalid_timestamp_rows"] += 1
        elif last is None or observed > last:
            last = observed
    counters["partial"] = any(
        value for key, value in counters.items() if key not in {"partial", "marker_rows"}
    )
    return (
        tuple(groups.values()),
        CandidateTokenQuality(**counters),
        last.isoformat().replace("+00:00", "Z") if last else None,
    )


def read_candidate_tokens(request: CandidateTokenReadRequest) -> CandidateTokenSnapshot:
    """Project observed provider reports without loading tasks or executing code."""
    request = CandidateTokenReadRequest.model_validate_json(request.model_dump_json())
    root, workspace = canonical(request.allowed_workspace_root), canonical(request.workspace)
    if not root.is_dir() or workspace == root or not workspace.is_relative_to(root):
        raise ValueError("workspace must be a strict descendant of an existing allowed root")
    observed_at = now()
    control = workspace / "candidate_run"
    try:
        saved = read_model(control / "request.json", CandidateRunRequest)
        initial = read_model(control / "launch.json", CandidateRunReceipt)
    except FileNotFoundError:
        return CandidateTokenSnapshot(
            run_id=request.expected_run_id,
            observed_at=observed_at,
            availability="unavailable",
            reason="native_evidence_unavailable",
        )
    if (
        Path(saved.preview.project_root) / saved.preview.document.definition.task.workspace
    ).resolve() != workspace:
        raise ValueError("native request workspace mismatch")
    try:
        receipt = read_model(control / "receipt.json", CandidateRunReceipt)
    except FileNotFoundError:
        receipt = None
    verify_candidate_records(
        saved,
        initial,
        expected_request=saved,
        expected_run_id=request.expected_run_id,
        workspace=workspace,
        receipt=receipt,
    )
    return read_ledger_snapshot(workspace, initial.run_id, initial.run_name, observed_at)


def read_ledger_snapshot(
    workspace: Path, run_id: str, run_name: str, observed_at: str
) -> CandidateTokenSnapshot:
    """Read one fixed ledger after the caller verifies its native identity."""
    try:
        payload, quality = ledger_prefix(workspace / "token_usage.jsonl")
    except FileNotFoundError:
        return CandidateTokenSnapshot(
            run_id=run_id,
            run_name=run_name,
            observed_at=observed_at,
            availability="unavailable",
            reason="usage_unavailable",
        )
    groups, quality, last = aggregate(payload, run_id=run_id, run_name=run_name, quality=quality)
    return CandidateTokenSnapshot(
        run_id=run_id,
        run_name=run_name,
        observed_at=observed_at,
        availability="available",
        reason="reported_responses" if groups else "no_reported_responses",
        groups=groups,
        quality=quality,
        last_valid_usage_at=last,
    )
