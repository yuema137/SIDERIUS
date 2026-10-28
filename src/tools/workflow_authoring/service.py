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
from workflows.definition import AuthoredWorkflowDocument, ReusableWorkflowDocument
from workflows.definition.draft import inspect_draft
from workflows.definition.source import (
    WorkflowSourceError,
    parse_workflow_source,
    render_workflow_source,
)

from .loop import loop_template, with_loop
from .models import (
    MAX_SOURCE_BYTES,
    AddNodeProposal,
    DocumentProposal,
    DraftProposal,
    DraftRequest,
    DraftView,
    LoopProposal,
    NodeDraftRequest,
    NodeDraftsProposal,
    NodeDraftsRequest,
    NodeDraftsView,
    NodeDraftView,
    Project,
    RemoveNodeProposal,
    ReviewRequest,
    ReviewView,
    SaveRequest,
    SaveView,
    SourceView,
)
from .node_edits import (
    NodeEditRefusal,
    add_node,
    apply_node_drafts,
    inspect_node,
    inspect_node_drafts,
    remove_node,
)
from .options import binding_projection, managed_roles
from .task_models import TaskReferenceReview, TaskReferenceTarget, TaskReferenceUpdateProposal
from .training import training_inspector
from .versions import (
    VersionDetail,
    VersionEntry,
    VersionList,
    VersionRecord,
    VersionRecordError,
    appended_record,
    encode_record,
    next_name,
    project_versions,
    read_record,
    read_recovery_copy,
    version_diff,
    version_record_path,
    write_record,
)


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def reviewed_source(
    base: SourceView, source: str, task_review: TaskReferenceReview | None = None
) -> ReviewView:
    """One exact source projection for review and retained publication refusals."""
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
    legacy_options, port_inventory = binding_projection(document)
    return ReviewView(
        source=source,
        sha256=digest(payload),
        diff=diff,
        document=document,
        binding_options=legacy_options,
        port_inventory=port_inventory,
        managed_roles=managed_roles(document),
        training=training_inspector(document),
        loop_template=loop_template(document),
        task_reference_update=task_review,
    )


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
    def __init__(self, project: Project, task_targets: tuple[TaskReferenceTarget, ...] = ()):
        self.task_targets = {
            target.choice_id: TaskReferenceTarget.model_validate_json(target.model_dump_json())
            for target in task_targets
        }
        if len(self.task_targets) != len(task_targets):
            raise ValueError("task reference choice IDs must be unique")
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
        legacy_options, port_inventory = binding_projection(document)
        return SourceView(
            project_id=self.project.project_id,
            source_path=str(self.project.source_file),
            source=source,
            sha256=digest(payload),
            document=document,
            binding_options=legacy_options,
            port_inventory=port_inventory,
            managed_roles=managed_roles(document),
            training=training_inspector(document),
            loop_template=loop_template(document),
        )

    def read(self) -> SourceView:
        return self._view(self._read_bytes()[0])

    def inspect_draft(self, request: DraftRequest) -> DraftView:
        """Inspect a non-executable draft without changing the canonical source."""
        request = DraftRequest.model_validate_json(request.model_dump_json())
        self._base(self._read_bytes()[0], request.expected_sha256)
        return DraftView(draft=request.draft, inspection=inspect_draft(request.draft))

    def inspect_node_draft(self, request: NodeDraftRequest) -> NodeDraftView:
        """Inspect a pending node (possibly with unbound inputs) without rendering a save."""
        request = NodeDraftRequest.model_validate_json(request.model_dump_json())
        self._base(self._read_bytes()[0], request.expected_sha256)
        return inspect_node(request.proposal)

    def inspect_node_drafts(self, request: NodeDraftsRequest) -> NodeDraftsView:
        """Inspect pending nodes/external inputs (possibly incomplete) without rendering a save."""
        request = NodeDraftsRequest.model_validate_json(request.model_dump_json())
        self._base(self._read_bytes()[0], request.expected_sha256)
        return inspect_node_drafts(request.proposal)

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
        if isinstance(proposal, DraftProposal):
            self._base(current_payload, request.expected_sha256)
            inspection = inspect_draft(proposal.draft)
            if inspection.document is None:
                raise AuthoringError(
                    "draft_" + inspection.status, "\n".join(inspection.diagnostics)
                )
            proposal = DocumentProposal(kind="document", document=inspection.document)
        task_review = None
        node_edit = None
        if isinstance(proposal, TaskReferenceUpdateProposal):
            from .task_references import review_task_references

            base = self._base(current_payload, request.expected_sha256)
            if not isinstance(base.document, ReusableWorkflowDocument):
                raise AuthoringError(
                    "task_reference_policy", "task-reference updates require reusable v2 source"
                )
            target = self.task_targets.get(proposal.selected_choice_id)
            if target is None:
                raise AuthoringError(
                    "task_reference_policy", "select a configured version-aware task choice"
                )
            try:
                updated, task_review = review_task_references(
                    base.document,
                    proposal,
                    tuple(self.task_targets.values()),
                    self.project.project_root,
                )
            except ValueError as error:
                raise AuthoringError("task_reference_policy", str(error)) from error
            source = render_workflow_source(updated)
        elif isinstance(proposal, LoopProposal):
            source = render_workflow_source(with_loop(proposal.source, proposal.loop))
        elif isinstance(proposal, (AddNodeProposal, NodeDraftsProposal, RemoveNodeProposal)):
            self._base(current_payload, request.expected_sha256)
            try:
                source, node_edit = (
                    add_node(proposal)
                    if isinstance(proposal, AddNodeProposal)
                    else apply_node_drafts(proposal)
                    if isinstance(proposal, NodeDraftsProposal)
                    else remove_node(proposal)
                )
            except NodeEditRefusal as error:
                raise AuthoringError(error.code, str(error)) from error
        else:
            source = (
                render_workflow_source(proposal.document)
                if isinstance(proposal, DocumentProposal)
                else proposal.source
            )
        review = reviewed_source(base, source, task_review)
        if node_edit is not None:
            review = review.model_copy(update={"node_edit": node_edit})
        if not isinstance(proposal, TaskReferenceUpdateProposal) and (
            request.task_reference_selection is not None
            or any(
                isinstance(value, ReusableWorkflowDocument) and value.task_binding is not None
                for value in (base.document, review.document)
            )
        ):
            base = self._base(current_payload, request.expected_sha256)
            if not isinstance(base.document, ReusableWorkflowDocument) or not isinstance(
                review.document, ReusableWorkflowDocument
            ):
                raise AuthoringError(
                    "task_reference_policy",
                    "task-reference publication requires reusable v2 source",
                )
            if request.task_reference_selection is None:
                raise AuthoringError(
                    "task_reference_policy",
                    "bound source requires explicit task-reference selection for review",
                )
            from .task_publication import review_publication

            try:
                task_review = review_publication(
                    base.document,
                    review.document,
                    request.task_reference_selection,
                    tuple(self.task_targets.values()),
                    self.project.project_root,
                )
            except ValueError as error:
                raise AuthoringError("task_reference_policy", str(error)) from error
            review = review.model_copy(update={"task_reference_update": task_review})
        try:
            self._base(
                self._read_bytes()[0] if task_review is not None else current_payload,
                request.expected_sha256,
            )
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
            bound = any(
                isinstance(document, ReusableWorkflowDocument) and document.task_binding is not None
                for document in (current.document, proposed)
            )
            if bound and request.task_reference_acceptance is None:
                raise AuthoringError(
                    "task_reference_acceptance",
                    "Bound workflow Save requires explicit task-reference findings acceptance; keep the reviewed draft",
                )
            if request.task_reference_acceptance is not None and (
                not isinstance(current.document, ReusableWorkflowDocument)
                or not isinstance(proposed, ReusableWorkflowDocument)
                or proposed.task_binding is None
            ):
                raise AuthoringError(
                    "task_reference_policy",
                    "pin removal or unbound task-reference publication is unsupported",
                )
            unchanged = previous == payload
            record = None if unchanged else self._next_record(previous, payload, request)
            recovery = () if unchanged else (self._recover(previous), self._recover(payload))
            self._verify_publication(current, proposed, request)
            final, final_mode = self._read_bytes()
            if final != previous or final_mode != mode:
                raise AuthoringError(
                    "conflict", "source changed before replacement", self._view(final)
                )
            if unchanged:
                return SaveView(sha256=digest(payload), recovery_ids=(), unchanged=True)
            publish_bytes_atomically(str(self.project.source_file), payload, mode=mode)
            assert record is not None
            record_bytes, record_mode, name = record
            try:
                write_record(
                    self.project.source_file,
                    record_bytes,
                    mode if record_mode is None else record_mode,
                )
            except (OSError, VersionRecordError) as error:
                raise AuthoringError(
                    "version_record_not_updated",
                    "Source saved, but its version record was not updated; the next Save "
                    "records this content as an unnamed observed version",
                    self._view(payload),
                ) from error
            return SaveView(sha256=digest(payload), recovery_ids=recovery, version_name=name)

    def _next_record(
        self, previous: bytes, payload: bytes, request: SaveRequest
    ) -> tuple[bytes, int | None, str]:
        """Validate the record and name before any write; refusal leaves every file intact."""
        try:
            record, mode = read_record(self.project.source_file)
            updated, name = appended_record(
                self.project.source_file,
                record,
                digest(previous),
                digest(payload),
                request.version_name,
            )
            return encode_record(updated), mode, name
        except VersionRecordError as error:
            raise AuthoringError("version_record", str(error)) from error

    def _version_rows(self) -> tuple[VersionRecord | None, bytes, tuple[VersionEntry, ...]]:
        current = self._read_bytes()[0]
        try:
            record = read_record(self.project.source_file)[0]
        except VersionRecordError as error:
            raise AuthoringError("version_record", str(error)) from error
        self._recovery_directory()
        recorded = {version.sha256 for version in record.versions} if record else set()
        available = {
            sha
            for sha in recorded
            if read_recovery_copy(self.project.recovery_directory, sha) is not None
        }
        available.add(digest(current))
        rows = project_versions(record, digest(current), frozenset(available))
        return record, current, rows

    def versions(self) -> VersionList:
        """Read-only history; a source without a record lists one unrecorded current row."""
        record, current, rows = self._version_rows()
        return VersionList(
            record_path=str(version_record_path(self.project.source_file)),
            record_present=record is not None,
            current_sha256=digest(current),
            next_name=next_name(record),
            versions=rows,
        )

    def version(self, index: int, expected_sha256: str) -> VersionDetail:
        """Read-only bytes of one listed version and its diff from the preceding row."""
        _, current, rows = self._version_rows()
        if not 0 <= index < len(rows) or rows[index].sha256 != expected_sha256:
            raise AuthoringError("conflict", "version history changed; list versions again")

        def content(row: VersionEntry) -> bytes | None:
            if row.sha256 == digest(current):
                return current
            return read_recovery_copy(self.project.recovery_directory, row.sha256)

        row = rows[index]
        previous = rows[index - 1] if index else None
        payload = content(row)
        before = content(previous) if previous is not None else None
        diff = None
        if payload is not None and before is not None and previous is not None:
            diff = version_diff(
                before,
                payload,
                f"{previous.name or 'unnamed'}/{previous.sha256[:12]}",
                f"{row.name or 'unnamed'}/{row.sha256[:12]}",
            )
        return VersionDetail(
            version=row,
            source=payload.decode("utf-8", errors="replace") if payload is not None else None,
            previous=previous,
            diff=diff,
        )

    def _verify_publication(
        self, current: SourceView, proposed: AuthoredWorkflowDocument, request: SaveRequest
    ) -> None:
        acceptance = request.task_reference_acceptance
        if acceptance is None:
            return
        assert isinstance(current.document, ReusableWorkflowDocument)
        assert isinstance(proposed, ReusableWorkflowDocument)
        from .task_publication import review_publication, verify_acceptance

        task_review = None
        try:
            task_review = review_publication(
                current.document,
                proposed,
                acceptance.selection,
                tuple(self.task_targets.values()),
                self.project.project_root,
            )
            verify_acceptance(task_review, acceptance)
        except ValueError as error:
            failure = AuthoringError("task_reference_publication", str(error), current)
            failure.proposal = reviewed_source(current, request.source, task_review)
            raise failure from error
