"""Transport active task bindings to native child command lines."""


def task_data_path_argv() -> list[str]:
    """The task-binding transport fragment — empty unless the run is BOUND.

    Step 10 / P1 C3. ``transport_argv`` and the three children's parsers were
    built together and then joined by nothing: the flag was parsed by every
    child and emitted by nobody, so every child took its regime-A branch. This
    is the emitter.

    The condition is :func:`active_task_data_path`, deliberately NOT
    ``resolve_bound_task_data_path``. The latter falls back to the
    compatibility implementation when nothing is bound, so using it here would
    put ``--task_data_path_id <compatibility id>`` into the argv of every
    legacy child — changing a command line that predates task binding, for
    runs that never composed anything. An un-composed run emits nothing and
    its children keep resolving through ``nullcontext``.

    The fragment is built from the RESOLVED implementation, so the id can only
    ever be the bound binding's own declared identity (the ``transport_argv``
    signature enforces that by taking the implementation, not a string).
    """
    from execute_tools.task_data_path import active_task_data_path, transport_argv

    bound = active_task_data_path()
    return transport_argv(bound) if bound is not None else []


def data_root_argv(flag: str) -> list[str]:
    """The physical-data-root transport fragment — empty unless BOUND.

    Step 11 C4 (R-11-7, R-11-8). Follows the ``--task_data_path_id``
    precedent exactly: emitted only when the run explicitly bound a root,
    so an un-composed run's argv is byte-identical to its pre-C4 form
    (R-11-1) and its children keep resolving through the import-time
    legacy fallback.

    ``flag`` differs per role because the CHILDREN's flags differ, and the
    difference is load-bearing rather than cosmetic:

    * training and inference read the dataset root from ``--data_dir``;
    * the scoring child's ``--data_dir`` is the **deliverable** directory
      (the parent already passes ``self.base_dir`` there), so its dataset
      root is ``--raw_data_dir``. Conflating the two would point the
      scorer's raw-baseline read at the sandbox.
    """
    from execute_tools.data_paths import active_physical_data_root

    bound = active_physical_data_root()
    return [flag, bound] if bound is not None else []


def task_manifest_argv() -> list[str]:
    """The composed run's manifest path — empty unless BOUND. Step 11 C5.

    Lets the SCORING child compose the run's DECLARED metric through the
    same authority the parent used, instead of unconditionally deriving
    TIDMAD's (`denoising_score_single.py:195`). Emitted only when composed,
    so legacy argv is byte-identical (R-11-1).

    Step 12 / PR-12bc C3 — now emitted to ALL THREE children. Step 11's note
    that "only scoring needs it" was true of the METRIC and false of the
    task data path: training and inference resolve a transported id through
    the registry, which holds only what their bootstrap imported, so an
    out-of-tree implementation resolved in the parent and failed in both of
    the children the parent spawned. The manifest is what lets them compose
    the declaration the parent composed, through the same authority.
    """
    from workflows.task_composition import active_task_manifest_path

    bound = active_task_manifest_path()
    return ["--task_manifest", bound] if bound is not None else []
