"""Fail-closed source identity prerequisites for composed tasks."""

from typing import Any

from execute_tools.task_data_path import TaskDataPath


def validate_composed_source_identity(
    impl: TaskDataPath,
    deliverable_naming: Any,
    resolved_manifest: str,
) -> str:
    """Require explicit artifact naming and registration-captured implementation identity."""
    from execute_tools.deliverable_spec import task_names_its_own_deliverables
    from execute_tools.task_data_path import registered_content_identity
    from workflows.task_composition import TaskCompositionError

    # arXiv #268 (the paper's discussion (13): "a fail-open default
    # inconsistent with the rest of the manifest's semantics; reported here
    # as a defect under repair" — this is the repair). A COMPOSED manifest
    # must either declare its indexed `deliverable:` naming or bind an
    # implementation that names its artifacts itself (module-level
    # `deliverable_name`, the F-A4-1 capability). Omission by a task with
    # NEITHER used to resolve the anchor task's shipped template silently —
    # the one manifest key whose omission took a default instead of refusing.
    # The legacy un-composed path is untouched (it is the anchor task's own
    # regime); every shipped composed manifest now satisfies one of the two
    # legal shapes.
    if deliverable_naming is None and not task_names_its_own_deliverables(impl):
        raise TaskCompositionError(
            f"manifest {resolved_manifest!r} declares no 'deliverable:' section and its "
            f"task_data_path {impl.task_data_path_id!r} does not name its own artifacts "
            "(no module-level deliverable_name). Omission used to resolve the anchor "
            "task's indexed template silently — a fail-open default the manifest's "
            "omission-vs-named-absence semantics forbid (arXiv #268). Declare "
            "'deliverable:' explicitly, or implement deliverable_name beside the "
            "task_data_path implementation."
        )

    # arXiv #255 — fail closed, never omit: by this line the implementation
    # has been RESOLVED, so its registration capture must exist. An absent
    # capture means the registration lifecycle broke; silently omitting the
    # content key would ship a fingerprint without the pin (the quiet
    # weakening the review criterion forbids), and recomputing from the file
    # here would be F-12bc-7 one layer up. Refuse and say why.
    impl_content_identity = registered_content_identity(impl.task_data_path_id)
    if impl_content_identity is None:
        raise TaskCompositionError(
            f"task_data_path {impl.task_data_path_id!r} resolved but has no "
            "registration-captured content identity; the fingerprint cannot "
            "pin the implementation's bytes. This is a registration-lifecycle "
            "defect, not a configuration error — refusing rather than "
            "composing an unpinned fingerprint (arXiv #255)."
        )

    return impl_content_identity
