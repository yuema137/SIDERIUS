"""Write-once workspace library and the profile/advice cards shown on the Settings page.

Uploads are validated by their owners before any write: ``parse_llm_config_bytes``
for LLM profiles and ``parse_advice_bytes`` for advice. A valid upload is published
once as ``library/<kind>/<slug>-<sha12>.json`` (mode 0600); the same bytes return the
existing ref, and nothing in the library is ever replaced or deleted.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Literal

from pydantic import Field

from tools.candidate_operations.models import OperationFailure
from tools.setup_review.route_models import LLMRoute
from tools.workflow_preview.models import PreviewModel

from .files import canonical, config_bytes
from .settings_file import SettingsInvalid, advice_bytes, library_directory
from .settings_models import FileRef, LibraryRef

LibraryKind = Literal["llm", "advice"]
ROUTE_ROLES = (
    "lit_review",
    "interpret",
    "data_analysis",
    "propose",
    "implement",
    "validate",
    "tune",
)


class LibraryUpload(PreviewModel):
    kind: LibraryKind
    label: str = Field(min_length=1, max_length=63)
    content: str  # UTF-8 text inside the 256 KiB request body


class ProfileCard(PreviewModel):
    label: str
    ref: FileRef
    routes: tuple[LLMRoute, ...] = ()
    required_names: tuple[str, ...] = ()  # credential names only, never values
    problem: str | None = None


class AdviceCard(PreviewModel):
    label: str
    ref: FileRef
    present_keys: tuple[str, ...] = ()
    unsupported_keys: tuple[str, ...] = ()
    problem: str | None = None


class LibraryRefused(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _profile(payload: bytes):
    from workflows.llm_config import parse_llm_config_bytes

    return parse_llm_config_bytes(payload)


def profile_card(label: str, ref: FileRef, path: Path) -> ProfileCard:
    """Routes and required credential names projected by their owners; never values."""
    from tools.candidate_worker.preflight import credential_requirements
    from tools.setup_review.routes import node_llm_routes

    try:
        config = _profile(config_bytes(str(path)))
    except (OSError, ValueError):
        return ProfileCard(label=label, ref=ref, problem="profile is unreadable or invalid")
    routes = tuple(route for role in ROUTE_ROLES for route in node_llm_routes(config, role))
    required = credential_requirements(routes, ()).required_names
    return ProfileCard(label=label, ref=ref, routes=routes, required_names=required)


def advice_card(label: str, ref: FileRef, path: Path) -> AdviceCard:
    import json

    from workflows.advice import ADVICE_KEYS_WITHOUT_REUSABLE_CARRIER, ADVICE_RECOGNISED_KEYS

    try:
        content = json.loads(advice_bytes(path, label=label))
    except (SettingsInvalid, ValueError):
        return AdviceCard(label=label, ref=ref, problem="advice file is unreadable or invalid")
    present = tuple(key for key in ADVICE_RECOGNISED_KEYS if key in content)
    return AdviceCard(
        label=label,
        ref=ref,
        present_keys=present,
        unsupported_keys=tuple(
            key for key in present if key in ADVICE_KEYS_WITHOUT_REUSABLE_CARRIER
        ),
    )


def slug(label: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:50].strip("-")
    if not value:
        raise LibraryRefused(422, "validation", "label needs at least one letter or digit")
    return value


def validate_upload(upload: LibraryUpload) -> bytes:
    """Owner validation before any write; messages name keys, never paths or values."""
    from workflows.advice import AdviceArtifactError, parse_advice_bytes

    payload = upload.content.encode()
    try:
        if upload.kind == "llm":
            _profile(payload)
        else:
            parse_advice_bytes(payload, label="upload")
    except AdviceArtifactError as error:
        raise LibraryRefused(422, "invalid_file", str(error)) from None
    except ValueError as error:
        raise LibraryRefused(422, "invalid_file", f"Not an LLM profile: {error}") from None
    return payload


def store(workspace: Path, upload: LibraryUpload) -> LibraryRef:
    """Publish once; identical bytes return the existing ref, different bytes are refused."""
    from core.durable_io import publish_bytes_write_once
    from core.generated_artifact_name import validate_generated_artifact_name

    payload = validate_upload(upload)
    digest = hashlib.sha256(payload).hexdigest()
    ref = LibraryRef(name=f"{slug(upload.label)}-{digest[:12]}.json", sha256=digest)
    validate_generated_artifact_name(ref.name, field="library name")
    try:
        directory = canonical(str(library_directory(workspace, upload.kind)))
    except OperationFailure:
        raise LibraryRefused(409, "unavailable", "the workspace library is unavailable") from None
    if not directory.is_dir():
        raise LibraryRefused(409, "unavailable", "the workspace library is unavailable; run init")
    try:
        publish_bytes_write_once(str(directory / ref.name), payload)
    except FileExistsError:
        try:
            existing = config_bytes(str(directory / ref.name))
        except (OSError, ValueError):
            existing = None
        if existing != payload:
            raise LibraryRefused(
                409,
                "exists",
                "a different library file already has this name; nothing was replaced",
            ) from None
    return ref
