"""Bounded read/review/save of one configured ordinary Python source file.

Advisory locks serialize cooperating clients. Noncooperating writes after the
final comparison can be lost and absent from recovery copies. Trusted local
parents are required; malicious same-user path swaps are outside this contract.
"""

import difflib
import fcntl
import hashlib
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from core.durable_io import publish_bytes_atomically, publish_bytes_write_once
from workflows.definition import ReusableWorkflowDocument
from workflows.definition.source import (
    WorkflowSourceError,
    parse_workflow_source,
    render_workflow_source,
)

from .models import (
    MAX_SOURCE_BYTES,
    DocumentProposal,
    Project,
    ReviewRequest,
    ReviewView,
    SaveRequest,
    SaveView,
    SourceView,
)
from .options import binding_options
from .training import training_inspector


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class AuthoringError(ValueError):
    def __init__(self, code: str, message: str, current: SourceView | None = None):
        self.code, self.current = code, current
        self.proposal: ReviewView | None = None
        super().__init__(message)


def checked_path(path: Path) -> None:
    if not path.is_absolute() or path != Path(os.path.abspath(path)):
        raise AuthoringError("path", "configured paths must be absolute and normalized")
    for part in (*reversed(path.parents), path):
        if part.is_symlink():
            raise AuthoringError("path", "symlink paths are unsupported")


class WorkflowAuthoring:
    def __init__(self, project: Project):
        self.project = Project.model_validate_json(project.model_dump_json())
        project = self.project
        for path in (project.project_root, project.source_file, project.recovery_directory):
            checked_path(path)
        root = project.project_root
        if not root.is_dir():
            raise AuthoringError("path", "project root must exist")
        if not all(
            path.is_relative_to(root) and path != root
            for path in (project.source_file, project.recovery_directory)
        ):
            raise AuthoringError("path", "source and recovery must be inside project root")
        if project.source_file.is_relative_to(project.recovery_directory):
            raise AuthoringError("path", "source must be outside recovery directory")
        self.lock = project.source_file.with_name(
            "." + project.source_file.name + ".authoring.lock"
        )
        self._recovery_directory()
        checked_path(project.source_file)
        self._source_mode(project.source_file.stat())

    def _recovery_directory(self) -> None:
        path = self.project.recovery_directory
        checked_path(path)
        info = path.stat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            raise AuthoringError("path", "recovery directory must be existing owner-only 0700")

    @staticmethod
    def _source_mode(info: os.stat_result) -> int:
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != os.getuid()
            or info.st_mode & 0o7000
        ):
            raise AuthoringError(
                "path", "source must be an owned single-link regular file without special bits"
            )
        return stat.S_IMODE(info.st_mode)

    def _read_bytes(self) -> tuple[bytes, int]:
        path = self.project.source_file
        checked_path(path)
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        with os.fdopen(os.open(path, flags), "rb") as handle:
            info = os.fstat(handle.fileno())
            mode = self._source_mode(info)
            payload = handle.read(MAX_SOURCE_BYTES + 1)
        if len(payload) > MAX_SOURCE_BYTES:
            raise AuthoringError("limit", "editor source exceeds 32 KiB UTF-8")
        try:
            payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise AuthoringError("encoding", "source must be UTF-8") from error
        return payload, mode

    def _view(self, payload: bytes) -> SourceView:
        source = payload.decode("utf-8")
        try:
            document = parse_workflow_source(source)
        except WorkflowSourceError as error:
            return SourceView(
                project_id=self.project.project_id,
                source_path=str(self.project.source_file),
                source=source,
                sha256=digest(payload),
                document=None,
                diagnostics=error.diagnostics,
            )
        return SourceView(
            project_id=self.project.project_id,
            source_path=str(self.project.source_file),
            source=source,
            sha256=digest(payload),
            document=document,
            binding_options=binding_options(document),
            training=training_inspector(document),
        )

    def read(self) -> SourceView:
        return self._view(self._read_bytes()[0])

    def _base(self, payload: bytes, expected: str) -> SourceView:
        current = self._view(payload)
        if current.sha256 != expected:
            raise AuthoringError(
                "conflict", "source changed; inspect current source and review again", current
            )
        if current.document is None:
            raise AuthoringError(
                "unsupported", "current source is read-only until repaired externally", current
            )
        return current

    def review(self, request: ReviewRequest) -> ReviewView:
        request = ReviewRequest.model_validate_json(request.model_dump_json())
        current_payload = self._read_bytes()[0]
        base = self._view(current_payload)
        proposal = request.proposal
        source = (
            render_workflow_source(proposal.document)
            if isinstance(proposal, DocumentProposal)
            else proposal.source
        )
        payload = source.encode("utf-8")
        if len(payload) > MAX_SOURCE_BYTES:
            raise AuthoringError("limit", "rendered editor source exceeds 32 KiB UTF-8")
        document = parse_workflow_source(source)
        diff = "".join(
            difflib.unified_diff(
                base.source.splitlines(True),
                source.splitlines(True),
                fromfile="current/workflow.py",
                tofile="proposed/workflow.py",
            )
        )
        review = ReviewView(
            source=source,
            sha256=digest(payload),
            diff=diff,
            document=document,
            binding_options=binding_options(document),
            training=training_inspector(document),
        )
        try:
            self._base(current_payload, request.expected_sha256)
        except AuthoringError as error:
            error.proposal = review
            raise
        return review

    @contextmanager
    def _locked(self) -> Iterator[None]:
        checked_path(self.lock)
        fd = os.open(self.lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600
            ):
                raise AuthoringError("path", "lock must be an owned single-link 0600 regular file")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise AuthoringError(
                    "busy", "another cooperating writer holds the source lock"
                ) from error
            yield
        finally:
            os.close(fd)

    def _recover(self, payload: bytes) -> str:
        self._recovery_directory()
        identity = digest(payload)
        path = self.project.recovery_directory / (identity + ".py")
        checked_path(path)
        try:
            publish_bytes_write_once(str(path), payload)
        except FileExistsError:
            info = path.lstat()
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600
            ):
                raise AuthoringError("recovery", "unsafe existing recovery file") from None
            with path.open("rb") as handle:
                if handle.read(MAX_SOURCE_BYTES + 1) != payload:
                    raise AuthoringError("recovery", "existing recovery copy differs") from None
        return identity

    def save(self, request: SaveRequest) -> SaveView:
        request = SaveRequest.model_validate_json(request.model_dump_json())
        payload = request.source.encode("utf-8")
        if digest(payload) != request.proposal_sha256:
            raise AuthoringError("proposal", "reviewed source hash does not match")
        proposed = parse_workflow_source(request.source)
        with self._locked():
            previous, mode = self._read_bytes()
            current = self._base(previous, request.expected_sha256)
            if any(
                isinstance(document, ReusableWorkflowDocument) and document.task_binding is not None
                for document in (current.document, proposed)
            ):
                raise AuthoringError(
                    "task_binding_unsupported",
                    "Bound workflow Save is unsupported until guarded task-reference publication is implemented; keep the reviewed draft",
                )
            if previous == payload:
                return SaveView(sha256=digest(payload), recovery_ids=(), unchanged=True)
            recovery = (self._recover(previous), self._recover(payload))
            final, final_mode = self._read_bytes()
            if final != previous or final_mode != mode:
                raise AuthoringError(
                    "conflict", "source changed before replacement", self._view(final)
                )
            publish_bytes_atomically(str(self.project.source_file), payload, mode=mode)
            return SaveView(sha256=digest(payload), recovery_ids=recovery)
