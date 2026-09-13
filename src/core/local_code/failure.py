"""Typed, launch-correlated task-code refusals; not a general error channel."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.generated_library import verified_chain_workspace
from core.local_code.capture import LocalCodeError

FAILURE_ENV = "SIDERIUS_TASK_CODE_FAILURE_CHANNEL"
REFUSAL_EXIT = 78


class CodeFailure(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    version: Literal["task-code-failure-v1"] = "task-code-failure-v1"
    kind: Literal["code_package_integrity"] = "code_package_integrity"
    launch_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    package_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    detail: str = Field(min_length=1)


class FailureChannel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    launch_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    package_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    transport_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    report_path: Path

    @model_validator(mode="after")
    def correlate_path(self) -> FailureChannel:
        if not self.report_path.is_absolute() or self.report_path.name != f"{self.launch_id}.json":
            raise ValueError("failure report must use its absolute launch-specific path")
        return self

    def failure(self, detail: str) -> CodeFailure:
        return CodeFailure(
            launch_id=self.launch_id, package_digest=self.package_digest, detail=detail
        )


def code_package_failure(exc: BaseException) -> LocalCodeError | None:
    """Only explicit wrapping preserves classification; implicit context does not."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, LocalCodeError):
            return current
        seen.add(id(current))
        current = current.__cause__
    return None


def raise_if_code_package_failure(exc: BaseException) -> None:
    failure = code_package_failure(exc)
    if failure is not None:
        raise failure


def read_failure_channel(environ: Mapping[str, str]) -> FailureChannel | None:
    from core.local_code.transport import DIGEST_ENV

    raw = environ.get(FAILURE_ENV)
    if raw is None:
        return None
    try:
        channel = FailureChannel.model_validate_json(raw)
        workspace = Path(verified_chain_workspace(environ=environ))
        expected = workspace / "task_code" / "failures" / f"{channel.launch_id}.json"
        if channel.report_path != expected or channel.transport_digest != environ.get(DIGEST_ENV):
            raise ValueError("failure descriptor differs from workspace/transport identity")
        return channel
    except (OSError, ValueError) as exc:
        raise LocalCodeError(f"code_package failure channel refused: {exc}") from exc


def new_failure_channel(environ: Mapping[str, str], package_digest: str) -> FailureChannel:
    from core.local_code.transport import DIGEST_ENV

    try:
        workspace = Path(verified_chain_workspace(environ=environ))
        launch_id = uuid4().hex
        return FailureChannel(
            launch_id=launch_id,
            package_digest=package_digest,
            transport_digest=environ[DIGEST_ENV],
            report_path=workspace / "task_code" / "failures" / f"{launch_id}.json",
        )
    except (KeyError, OSError, ValueError) as exc:
        raise LocalCodeError(f"code_package cannot prepare failure channel: {exc}") from exc


def read_failure(channel: FailureChannel) -> CodeFailure | None:
    try:
        payload = channel.report_path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise LocalCodeError(f"code_package failure report unavailable: {exc}") from exc
    try:
        report = CodeFailure.model_validate_json(payload)
        if report.launch_id != channel.launch_id or report.package_digest != channel.package_digest:
            raise ValueError("report differs from expected launch/package identity")
        return report
    except ValueError as exc:
        raise LocalCodeError(f"code_package failure report refused: {exc}") from exc


def publish_failure(channel: FailureChannel, exc: LocalCodeError) -> None:
    """Atomic first-refusal publication; siblings cannot replace its diagnosis."""
    report = channel.failure(str(exc))
    path = channel.report_path
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".failure-", delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(report.model_dump_json().encode())
            handle.flush()
            os.fsync(handle.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                read_failure(channel)  # A prior valid sibling refusal wins.
        finally:
            temporary.unlink()


def check_child_failure(channel: FailureChannel | None, returncode: int | None = None) -> None:
    if channel is None:
        return
    report = read_failure(channel)
    if report is None and returncode == REFUSAL_EXIT:
        report = channel.failure("code_package guard refused; its failure report is unavailable")
    if report is not None:
        raise LocalCodeError(report.detail, report=report)
