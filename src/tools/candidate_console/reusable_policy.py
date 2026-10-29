"""Admission policy before preparation verification may read external observations."""

from pathlib import Path
from uuid import UUID

from tools.candidate_operations.models import OperationFailure
from tools.candidate_prepare.models import CandidatePreparationRequest
from tools.candidate_prepare.reusable_models import ReusableBindingInspection
from tools.workflow_authoring.models import Project

from .files import canonical
from .models import TaskChoice
from .setups import SetupRegistry


def configured_capture(
    setups: SetupRegistry, project_id: str, task_id: str
) -> tuple[Project, TaskChoice, Path]:
    config = setups.config
    setup = setups.runnable(project_id)
    # A console-created setup is bound to one task; a run may not borrow another's policy.
    if setup.task_id is not None and setup.task_id != task_id:
        raise OperationFailure("task_policy", "experiment setup belongs to another task")
    project = setup.project
    task = next((t for t in config.tasks if t.task_id == task_id), None)
    if task is None or task.reusable_runs_root is None:
        raise OperationFailure("task_policy", "task has no configured reusable runs root")
    root = canonical(task.reusable_runs_root)
    store = config.operation_store
    if not root.is_dir() or any(
        not any(root.is_relative_to(canonical(parent)) for parent in roots)
        for roots in (store.preparation_roots, store.candidate_roots)
    ):
        raise OperationFailure("task_policy", "reusable root is unavailable or outside policy")
    return project, task, root


def capture_path(root: Path, run_id: UUID) -> Path:
    return canonical(str(root / str(run_id)))


def check_capture_policy(
    project: Project, task: TaskChoice, inspected: ReusableBindingInspection
) -> None:
    """Compare typed pinned metadata only; never read mutable authored source."""
    binding = inspected.binding
    request = binding.request
    if binding.project_root != str(project.project_root) or binding.original_source.path != str(
        project.source_file
    ):
        raise OperationFailure("task_policy", "capture belongs to another source or project")
    check_request_policy(task, request)
    # Even self-consistent binding/control metadata cannot authorize an external read.
    if tuple((item.reference, item.path) for item in inspected.control.sources) != (
        ("task.manifest", task.task_manifest),
        ("llm_config", task.llm_config_file),
    ):
        raise OperationFailure("task_policy", "captured external observations differ from policy")


def check_request_policy(task: TaskChoice, request: CandidatePreparationRequest) -> None:
    """One resource/options comparison for source inspection and captured metadata."""
    fields = (
        "task_manifest",
        "data_root",
        "llm_config_file",
        "task_read_only",
        "preparation_timeout_seconds",
        "candidate_timeout_seconds",
        "candidate_network",
        "candidate_devices",
        "candidate_environment_names",
    )
    if any(getattr(request, name) != getattr(task, name) for name in fields):
        raise OperationFailure("task_policy", "captured task or resources differ from policy")
    if (
        task.allowed_output_types is not None
        and request.allowed_output_types != task.allowed_output_types
    ):
        raise OperationFailure("task_policy", "captured output restriction differs from policy")
