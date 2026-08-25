"""Where an attempt's task scopes come from — PRIVATE to this node.

Step 12 / PR-12bc B5 (CAP-SCOPE). The typed boundary ``prepare_attempt``
CALLS, rather than a branch family grown inside it (§J: "scope acquisition is
a NEW typed boundary CALLED from planning — never inline branching").

```text
un-composed   ->  nothing acquired; the legacy sample sets are the scope
composed      ->  the BOUND implementation builds this attempt's scopes,
                  through its optional TaskScopeCapability
```

**Discrimination is by composition PRESENCE, never by task name** — the same
rule every other composed-path decision in this repository follows.
``agent_input.task_composition_ref is not None`` is the signal PR-12a already
established (`ml_hyperparameter_tune_agent.py:687`).

**Why the legacy sample sets survive on BOTH paths here** (D-BC-13, recorded
in the design ledger): they are consumed by the training spawn
(`runtime.py:875`), both inference spawns (`execution.py:992`, `:1038`) and the
validation-expectation decision (`execution.py:716`). Making them ``None`` on
the composed path at THIS commit would break a composed run before any
replacement existed. B6 flips those consumers to the transported scope; the
"``build_sample_set`` was not called" spy belongs there, where it is true.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from execute_tools.dataset_config import (
    DataScope,
    DatasetProfile,
    declares_tidmad_topology,
    tidmad_topology,
)
from execute_tools.task_data_path import (
    ScopeBuildRequest,
    TaskDataPathResolutionError,
    require_bound_task_data_path,
    resolve_task_scope_capability,
)


class TaskTopologyUnavailableError(RuntimeError):
    """A caller asked for physical geometry this run's task does not declare.

    Step 12 / PR-12d, seam B. Raised only where a bound genuinely cannot be
    supplied and the caller has no legal way to continue. Every other consumer
    of :class:`AttemptTopologyFacts` **skips or declines by name** instead —
    the D-BC-8 precedent, where the partition bound is generic identity and is
    always checked while the per-partition bound is task topology and is
    SKIPPED, never guessed.
    """


class AttemptTopologyFacts(BaseModel):
    """What the tuner's own paths still need to know about physical geometry.

    Step 12 / PR-12d, seam B. Five sites in this package decoded TIDMAD's
    topology directly — ``planning.py`` 381/460/465,
    ``ml_hyperparameter_tune_agent.py`` 758 and ``execution.py`` 1066 — and
    each one killed a composed contrast run before any training. The defect
    was never "N calls to ``tidmad_topology``": it was that a composed run
    **already has a bound scope capability while planning and execution
    separately construct TIDMAD facts**.

    ```text
    COMPOSED            -> the bound task scope / capability is authoritative
    LEGACY / UNCOMPOSED -> the existing TIDMAD regime-A construction remains
                           authoritative
    ```

    **Legacy values arrive BY CONSTRUCTION, not via a parallel branch.** The
    projection asks the profile what it declares; a TIDMAD profile always
    declares physical geometry, so every legacy caller receives exactly the
    object it received before. There is deliberately no ``if composed:`` here
    and no task name: what discriminates is what the PROFILE declares, which
    is a stronger statement than composition presence — a composed TIDMAD run
    is still physical, and that is the honest answer for it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    physical_dataset: Any = Field(
        default=None,
        description=(
            "The run's TIDMAD ``DatasetConfig`` when the profile declares "
            "TIDMAD's physical topology, else ``None`` — a DECLARED absence, "
            "not a missing value."
        ),
    )

    @property
    def declares_physical_geometry(self) -> bool:
        return self.physical_dataset is not None

    def require_physical_dataset(self, purpose: str) -> Any:
        """The dataset config, or a refusal that NAMES what was unavailable."""
        if self.physical_dataset is None:
            raise TaskTopologyUnavailableError(
                f"{purpose} requires this run's physical dataset geometry, and "
                f"the run's task declares none. A composed task that is not "
                f"TIDMAD-shaped has no PSD segment length, no segments per "
                f"file and no validation-file template — and inventing them is "
                f"what the Q-12-4 profile split exists to prevent."
            )
        return self.physical_dataset


def project_attempt_topology_facts(profile: DatasetProfile) -> AttemptTopologyFacts:
    """The ONE place the tuner package decodes physical topology.

    A MEMBERSHIP test decides whether the profile declares one; a profile that
    declares the sections but carries a MALFORMED payload still raises out of
    :func:`tidmad_topology`, because that is a broken declaration rather than
    an absent one.
    """
    if not declares_tidmad_topology(profile):
        return AttemptTopologyFacts()
    return AttemptTopologyFacts(physical_dataset=tidmad_topology(profile).dataset)


class AttemptScopes(BaseModel):
    """The task-built scopes for one attempt, or their declared absence.

    ``None`` on both legs means "this run is not composed", which is a
    STATEMENT, not a missing value: the un-composed path has no task scope
    because the task was never asked for one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    training: Any = Field(
        default=None,
        description="The task's own training scope object — OPAQUE to this node.",
    )
    evaluation: Any = Field(
        default=None,
        description="The task's own evaluation scope object — OPAQUE to this node.",
    )

    @property
    def acquired(self) -> bool:
        return self.training is not None


#: Framework knobs -> the capability's request. Named here so the mapping is
#: one readable table rather than an argument list at a call site.
def _request_for(
    *,
    round_kind: str,
    strategy: str,
    portion: float,
    seed: int | None,
    subset_ref: str | None,
    target_partitions: tuple[int, ...],
    max_samples: int | None,
    task_parameters: dict[str, Any],
) -> ScopeBuildRequest:
    return ScopeBuildRequest(
        round_kind=round_kind,  # type: ignore[arg-type]
        selection_strategy=strategy,  # type: ignore[arg-type]
        portion=portion,
        seed=seed,
        subset_ref=subset_ref,
        target_partitions=target_partitions,
        max_samples=max_samples,
        task_parameters=task_parameters,
    )


def acquire_attempt_scopes(
    *,
    composed: bool,
    mode: str,
    trial_strategy: str,
    trial_portion: float,
    eval_strategy: str,
    eval_portion: float,
    train_sampling_seed: int | None,
    eval_sampling_seed: int | None,
    target_files: Sequence[int] | None,
    subset: DataScope | None,
    validation_max_samples: int | None,
    task_parameters: dict[str, Any],
) -> AttemptScopes:
    """Build this attempt's task-owned scopes, or declare that there are none.

    Every SELECTION KNOB is a value ``prepare_attempt`` already holds, so what
    a scope was built FROM is visible at the call site. The bound
    implementation itself is resolved here rather than threaded, because it is
    a run-scoped AUTHORITY and not an input — and it is resolved only after
    ``composed`` has established that there is one.

    Args:
        composed: Whether this run has a bound task composition. The ONLY
            discriminator; there is deliberately no task name anywhere here.
        mode: The round's identity — ``"trial"`` / ``"formal"`` /
            ``"single_file"``. ``single_file`` acquires nothing: that legacy
            mode sets both sample sets to ``None`` and never asks a task for a
            scope (`planning.py:423-424`).
        trial_strategy / trial_portion / train_sampling_seed: the TRAINING
            leg's resolved selection knobs — the same values the legacy path
            passes to ``build_sample_set``.
        eval_strategy / eval_portion / eval_sampling_seed: the EVAL leg's.
        target_files: the explicitly named subset for the ``target``
            strategy, or ``None``/empty. NORMALIZED here rather than at the
            call site, so ``prepare_attempt`` gains a CALL and not two more
            conditional expressions (§J).
        subset: the operator's partition restriction, spelled opaquely for
            the task by :meth:`DataScope.to_cli`. Also normalized here.
        validation_max_samples: the eval leg's row ceiling (07c C6).
        task_parameters: OPAQUE per-attempt task knobs (D-BC-1a).

    Returns:
        The built scopes, or an empty :class:`AttemptScopes` when the run is
        un-composed or the round is ``single_file``.

    Raises:
        TaskScopeCapabilityError: The run is composed and needs task-owned
            scopes, but the bound implementation declares no capability.
            Raised HERE — parent-side, while the attempt is being prepared —
            so the refusal happens at composition rather than at first spawn.
    """
    if not composed or mode not in ("trial", "formal"):
        return AttemptScopes()

    partitions = tuple(target_files or ())
    subset_ref = subset.to_cli() if subset is not None else None

    # PRESENCE came from the caller's INPUT PROJECTION (PR-12a C2's rule, and
    # a census over this package enforces it — ``active_task_data_path`` is an
    # AMBIENT read and must not appear here). The IMPLEMENTATION is resolved
    # only once presence is established, so an un-composed run never acquires a
    # registration requirement it did not have.
    try:
        bound = require_bound_task_data_path()
    except TaskDataPathResolutionError as exc:
        # A composed run whose data-path binding cannot resolve is a
        # contradiction, not a regime-A run: the composition is what declared
        # the task.
        raise RuntimeError(
            f"a composed run reached scope acquisition with no resolvable task "
            f"data path ({exc}). The composition binding is what names the "
            f"task, so this is a wiring contradiction rather than a legacy run."
        ) from exc
    capability = resolve_task_scope_capability(bound)

    training = capability.build_training_scope(
        _request_for(
            round_kind=mode,
            strategy=trial_strategy,
            portion=trial_portion,
            seed=train_sampling_seed,
            subset_ref=subset_ref,
            target_partitions=partitions,
            max_samples=None,
            task_parameters=task_parameters,
        )
    )
    evaluation = capability.build_eval_scope(
        _request_for(
            round_kind=mode,
            strategy=eval_strategy,
            portion=eval_portion,
            seed=eval_sampling_seed,
            subset_ref=subset_ref,
            target_partitions=partitions,
            # The ceiling bounds the EVAL request only (07c C6); a training
            # scope carrying it would silently shrink training too.
            max_samples=validation_max_samples,
            task_parameters=task_parameters,
        )
    )
    return AttemptScopes(training=training, evaluation=evaluation)
