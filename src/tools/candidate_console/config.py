"""Validate inert operator resources without composing tasks or constructing clients."""

from dataclasses import replace
from pathlib import Path

from core.runtime_control.budget_intake import HostBudgetFileError, load_host_budget_file
from tools.candidate_operations.host_ledger import HostScheduling, ledger_directory
from tools.candidate_operations.models import OperationFailure

from .config_errors import MissingConfigFile
from .files import canonical, config_bytes, credential_values, token
from .models import ConsoleConfig
from .settings_models import ResolvedConsole


def validate_config(config: ConsoleConfig, *, workspace: Path | None = None) -> ConsoleConfig:
    """Validate inert facts; ``workspace`` adds its settings and library to protected paths."""
    from tools.candidate_prepare.admission import validate_read_only_exclusion

    from .settings_file import SettingsInvalid, protected_paths

    config = ConsoleConfig.model_validate_json(config.model_dump_json())
    store = config.operation_store
    canonical(store.state_root)
    for root in (*store.preparation_roots, *store.candidate_roots):
        if not canonical(root).is_dir():
            raise ValueError("configured output roots must exist")
    for task in config.tasks:
        for root, allowed in (
            (task.preparation_root, store.preparation_roots),
            (task.candidate_root, store.candidate_roots),
        ):
            path = canonical(root)
            if not path.is_dir() or not any(
                path.is_relative_to(Path(parent)) for parent in allowed
            ):
                raise ValueError("task output root is outside operation store roots")
        if task.reusable_runs_root is not None:
            path = canonical(task.reusable_runs_root)
            state = canonical(store.state_root)
            if (
                not path.is_dir()
                or any(
                    not any(path.is_relative_to(canonical(parent)) for parent in roots)
                    for roots in (store.preparation_roots, store.candidate_roots)
                )
                or path.is_relative_to(state)
                or state.is_relative_to(path)
            ):
                raise ValueError(
                    "reusable runs root must be separate from state and within both output scopes"
                )
        if not canonical(task.data_root).is_dir():
            raise ValueError("configured data root must exist")
        protected = protected_paths(config, workspace)
        for label, paths in (
            (f"data folder for task {task.task_id}", (task.data_root,)),
            (f"read-only dependency of task {task.task_id}", task.task_read_only),
        ):
            try:
                validate_read_only_exclusion(tuple(map(Path, paths)), protected)
            except ValueError:
                raise SettingsInvalid(f"{label} overlaps a protected console path") from None
        for field in ("task_manifest", "llm_config_file"):
            name = getattr(task, field)
            path = canonical(name)
            if not path.exists():
                raise MissingConfigFile(f"task {task.task_id}", field, name)
            if not path.is_file():
                raise ValueError("configured resource must be a file")
        for name in task.task_read_only:
            if not canonical(name).exists():
                raise ValueError("configured dependency must exist")
    for choice in config.native_chain_choices:
        request = choice.request
        for path in (request.capture_path, request.envelope, *request.read_only, *request.devices):
            canonical(path)
    candidate_roots = tuple(canonical(root) for root in store.candidate_roots)
    for example in config.recorded_examples:
        workspace = canonical(example.workspace)
        if not workspace.is_dir() or not any(
            workspace != root and workspace.is_relative_to(root) for root in candidate_roots
        ):
            raise ValueError("recorded example workspace must be inside a candidate root")
    if config.editor_projects:
        from tools.workflow_authoring.service import WorkflowAuthoring

        for project in config.editor_projects:
            try:
                WorkflowAuthoring(project)
            except FileNotFoundError:
                # Report only the configured source, not arbitrary exception text.
                if not project.source_file.exists():
                    raise MissingConfigFile(
                        f"editor project {project.project_id}", "source", str(project.source_file)
                    ) from None
                raise
            for output in (*store.preparation_roots, *store.candidate_roots):
                output_path = Path(output)
                recovery = project.recovery_directory
                if recovery.is_relative_to(output_path) or output_path.is_relative_to(recovery):
                    raise ValueError("editor recovery must be separate from run output roots")
    token(config.auth_token_file)
    if config.credential_file is not None:
        # Validate private file facts and JSON/dotenv shape, without selecting/printing values.
        credential_values(config.credential_file)
    return config


def host_scheduling(config: ConsoleConfig) -> HostScheduling | None:
    """Load the configured host ledger once (B3-4c); ``None`` keeps every launch serial.

    The directory must already exist with owned mode 0700 (``ledger_directory``);
    the budget file is read only through ``load_host_budget_file``. Either
    failure stops the console from starting rather than launching unbudgeted.
    """
    selection = config.host_ledger
    if selection is None:
        return None
    try:
        ledger_directory(selection.ledger_root)
        budget = load_host_budget_file(Path(selection.budget_file).absolute())
    except (OperationFailure, HostBudgetFileError) as error:
        raise ValueError(f"configured host ledger is unusable: {error}") from error
    return HostScheduling(ledger_root=selection.ledger_root, budget=budget)


def load_config(path: str) -> ConsoleConfig:
    return validate_config(ConsoleConfig.model_validate_json(config_bytes(path)))


def load_console(path: str) -> ResolvedConsole:
    """Resolve omitted layout locations, then apply the unchanged ``validate_config``."""
    from .workspace import resolve_console

    resolved = resolve_console(config_bytes(path))
    context = replace(resolved.settings, console_path=canonical(path))
    return validate_resolved(ResolvedConsole(resolved.config, context))


def validate_resolved(resolved: ResolvedConsole) -> ResolvedConsole:
    """``validate_config`` with workspace protection, then settings certification."""
    from .settings_file import validate_settings

    config = validate_config(resolved.config, workspace=resolved.settings.workspace_root)
    resolved = ResolvedConsole(config, resolved.settings)
    validate_settings(resolved)
    return resolved
