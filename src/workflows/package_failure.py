"""Root-owned chain halt for a declared package refusal, separate from measurement."""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from core.local_code.failure import CodeFailure, code_package_failure


class PackageHalt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    reason: Literal["code_package_integrity"] = "code_package_integrity"
    halted_at: datetime
    workspace: Path
    iteration: int
    detail: str
    failure: CodeFailure | None = None


def halt_on_package_failure(
    exc: BaseException,
    *,
    workspace: str,
    iteration: int,
    write_marker: Callable[[str, dict[str, Any]], str],
) -> None:
    """Reuse the existing marker owner and exit3; ordinary errors are untouched."""
    refusal = code_package_failure(exc)
    if refusal is None:
        return
    payload = PackageHalt(
        halted_at=datetime.now(UTC),
        workspace=Path(workspace).absolute(),
        iteration=iteration,
        detail=str(refusal),
        failure=refusal.report,
    )
    try:
        payload.workspace.mkdir(parents=True, exist_ok=True)
        write_marker(str(payload.workspace), payload.model_dump(mode="json", exclude_none=True))
    except OSError as marker_error:
        # A broken filesystem cannot guarantee queued-job persistence. It must
        # still not turn this foreground halt into an ordinary retry exit.
        print(f"[HALT] package failure marker unavailable: {marker_error}", file=sys.stderr)
    print(f"[HALT] code_package_integrity: {refusal}", file=sys.stderr)
    raise SystemExit(3)
