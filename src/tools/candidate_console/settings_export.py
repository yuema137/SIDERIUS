"""Native-format export of a saved workflow with its task's LLM profile and inline advice.

``<workspace>/exported_configs/<name>/`` (0700) receives write-once files:
``workflow.py`` (the saved source bytes, verified against the browser's sha256),
``llm.json`` (the task's effective ``llm_config_file`` bytes, valid for CLI
``--llm_config``) and, only when the workflow carries inline advice, ``advice.json``
in the CLI advice format, validated by ``parse_advice_bytes`` before it is written.
There is no envelope schema and no credential, token or credential path. A taken
name is refused with a free suggestion; nothing is overwritten or deleted.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Literal

from pydantic import Field

from tools.workflow_preview.models import PreviewModel

from .files import config_bytes, open_directory
from .models import ConsoleConfig
from .settings_models import Id

EXPORT_DIRECTORY = "exported_configs"
ExportFile = Literal["workflow.py", "llm.json", "advice.json"]
DOWNLOAD_LIMIT = 1024 * 1024
# Inline workflow carrier -> CLI advice key (design §3.3 carrier mapping).
ADVICE_CARRIERS = (
    ("proposal_advice", "propose"),
    ("implementation_advice", "implement"),
    ("validation_advice", "validate"),
)


class ExportRequest(PreviewModel):
    project_id: Id
    task_id: Id
    name: Id
    expected_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ExportResult(PreviewModel):
    name: str
    files: tuple[ExportFile, ...]


class ExportRefused(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def inline_advice(document: object) -> bytes | None:
    """CLI-format advice from the workflow's own carriers; ``None`` when it has none."""
    from workflows.advice import AdviceArtifactError, parse_advice_bytes
    from workflows.definition import ReusableWorkflowDocument

    if not isinstance(document, ReusableWorkflowDocument):
        return None
    options = document.preparation_options
    advice = {
        key: value
        for field, key in ADVICE_CARRIERS
        if isinstance(value := getattr(options, field), str) and value.strip()
    }
    launch = (document.training_settings or {}).get("launch")
    tune = launch.get("human_advice_tune") if isinstance(launch, dict) else None
    if isinstance(tune, str) and tune.strip():
        advice["tune"] = tune
    if not advice:
        return None
    payload = (json.dumps(advice, indent=2, ensure_ascii=False) + "\n").encode()
    try:
        parse_advice_bytes(payload, label="exported advice")
    except AdviceArtifactError as error:
        raise ExportRefused(422, "invalid_advice", str(error)) from None
    return payload


def _write_once(directory: int, name: str, payload: bytes) -> None:
    descriptor = os.open(
        name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory
    )
    try:
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _free_name(exports: int, name: str) -> str:
    for index in range(2, 1000):
        candidate = f"{name}-{index}"[:80]
        try:
            os.stat(candidate, dir_fd=exports, follow_symlinks=False)
        except FileNotFoundError:
            return candidate
    return f"{name}-new"


def export(config: ConsoleConfig, workspace: Path, request: ExportRequest) -> ExportResult:
    from tools.workflow_authoring.service import AuthoringError, WorkflowAuthoring

    from .workspace import ensure_owned_directory

    request = ExportRequest.model_validate_json(request.model_dump_json())
    project = next((p for p in config.editor_projects if p.project_id == request.project_id), None)
    task = next((t for t in config.tasks if t.task_id == request.task_id), None)
    if project is None or task is None:
        raise ExportRefused(404, "not_found", "project or task is not configured")
    try:
        view = WorkflowAuthoring(project).read()
    except (AuthoringError, OSError, ValueError):
        raise ExportRefused(409, "unavailable", "the saved workflow is unavailable") from None
    source = view.source.encode()
    if view.sha256 != request.expected_source_sha256 or (
        hashlib.sha256(source).hexdigest() != request.expected_source_sha256
    ):
        raise ExportRefused(409, "stale", "the saved workflow changed; reload it and export again")
    try:
        profile = config_bytes(task.llm_config_file)
    except (OSError, ValueError):
        raise ExportRefused(409, "unavailable", "the task's LLM profile is unavailable") from None
    files: dict[ExportFile, bytes] = {"workflow.py": source, "llm.json": profile}
    advice = inline_advice(view.document)
    if advice is not None:
        files["advice.json"] = advice
    try:
        root = open_directory(workspace)
        try:
            exports = ensure_owned_directory(root, EXPORT_DIRECTORY, EXPORT_DIRECTORY)
        finally:
            os.close(root)
    except (OSError, ValueError):
        raise ExportRefused(
            409, "unavailable", "exported_configs is unavailable, linked or not yours"
        ) from None
    try:
        try:
            os.mkdir(request.name, 0o700, dir_fd=exports)
        except FileExistsError:
            raise ExportRefused(
                409,
                "exists",
                "export name is taken; exports are never overwritten, including one left by "
                f"an interrupted export. Try {_free_name(exports, request.name)}",
            ) from None
        target = os.open(request.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=exports)
        try:
            os.fchmod(target, 0o700)
            for name, payload in files.items():
                _write_once(target, name, payload)
        finally:
            os.close(target)
    finally:
        os.close(exports)
    return ExportResult(name=request.name, files=tuple(files))


def download(workspace: Path, name: str, file: ExportFile) -> bytes:
    """Bytes of one exported file, opened no-follow beneath the export directory."""
    try:
        directory = open_directory(workspace / EXPORT_DIRECTORY / name)
    except OSError:
        raise ExportRefused(404, "not_found", "export is unavailable") from None
    try:
        descriptor = os.open(file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except OSError:
        raise ExportRefused(404, "not_found", "export file is unavailable") from None
    finally:
        os.close(directory)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ExportRefused(404, "not_found", "export file is unavailable")
        payload = stream.read(DOWNLOAD_LIMIT + 1)
    if len(payload) > DOWNLOAD_LIMIT:
        raise ExportRefused(404, "not_found", "export file is unavailable")
    return payload
