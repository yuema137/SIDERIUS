"""Task-dependent standard-workflow decisions, without workflow execution."""

from execute_tools.dataset_config import resolve_dataset_profile


def resolve_analysis_binding(task_composition, enabled: bool | None):
    """Resolve the workflow treatment against the task-owned binding.

    A launch flag transports an experiment's treatment; it never constructs
    missing task authority or changes the standalone agent contract.
    """

    binding = getattr(task_composition, "data_analysis", None)
    if enabled is True and binding is None:
        raise ValueError(
            "data_analysis_enabled=True requires a task-composed data_analysis binding"
        )
    return None if enabled is False else binding


def _refuse_data_scope_for_a_foreign_topology(scope_is_partial: bool, task_composition) -> None:
    """`--data_scope` names FILE INDICES; refuse it for a task without them.

    Step 12 / PR-12bc B7 (§D.4). Extracted rather than inlined: `run_workflow`
    carries a §12.1 branch tripwire, and this check is a self-contained
    decision with its own reason — exactly the shape that belongs behind a
    call.

    `--data_scope` is TIDMAD/legacy vocabulary. Silently resolving it against a
    composed task's partition count would restrict a run to partitions the
    operator never meant. Refused BY NAME, at startup, before an LLM call or a
    GPU minute. Composed TIDMAD keeps honouring it through its own capability,
    which is why the discriminator is "does this task declare TIDMAD's
    topology" and never a task name.
    """
    if not scope_is_partial or task_composition is None:
        return
    from execute_tools.dataset_config import tidmad_topology

    try:
        tidmad_topology(resolve_dataset_profile())
    except ValueError as exc:
        raise ValueError(
            f"--data_scope names FILE INDICES, which is legacy vocabulary this "
            f"composed task does not share ({exc}). Declare the restriction "
            f"through the task's own scope capability instead; a file-index "
            f"list cannot be reinterpreted for a task with a different "
            f"partition concept."
        ) from exc


def validate_scope_settings(
    *,
    scope_is_partial: bool,
    formal_strategy: str,
    task_composition,
    health_gate_enabled: bool,
    health_gate_files: list[int] | None,
) -> None:
    """Apply the standard workflow's existing partial-scope startup contract."""
    if scope_is_partial and formal_strategy != "snapshot":
        raise ValueError(
            f"partial data_scope requires formal_strategy='snapshot' "
            f"(got {formal_strategy!r}). Operator configuration is a "
            f"contract — it is never normalized."
        )
    _refuse_data_scope_for_a_foreign_topology(scope_is_partial, task_composition)
    if health_gate_enabled and scope_is_partial and health_gate_files is None:
        raise ValueError(
            "partial data_scope with HealthGates enabled requires an "
            "explicit health_gate_files list (there is no automatic "
            "default). Pass health_gate_files ⊆ the scope, or disable "
            "the subsystem with health_gate_enabled=False."
        )
