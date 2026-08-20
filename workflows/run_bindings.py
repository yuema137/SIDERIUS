"""``WorkflowRunBindings`` — the authorities one exploration run established.

Step 09.5a finding A-1. ``run_workflow`` resolved its run-scoped authorities —
the data scope, the run invariants, the hardware context, the metric spec, the
reasoning pipeline — into bare locals interleaved with 99 parameters and eleven
mutable accumulators. Nothing distinguished "settled once at startup" from
"changes as the run proceeds", so Step 10's launcher-owned task binding would
have landed in the same undifferentiated scope.

MEMBERSHIP RULE — the only one
-------------------------------
    an authority or invariant this run established during startup,
    whose identity does not change for the rest of the run.

A value that varies per iteration does not belong here even if passing it would
be convenient. That is enforced, not merely documented: :meth:`__post_init__`
refuses any field name that :class:`core.chain_state.ChainState` declares.

NOT A SERVICE LOCATOR (operator Amendment A)
---------------------------------------------
Three capability references live here — ``bridge_factory``, ``sandbox_factory``
and ``measurement_capability`` — and each was audited individually before being
admitted. The first two are function references; the third is a Pydantic model
with ``frozen=True, extra="forbid"``. None of them has mutable state this
carrier owns, and this carrier never calls a lifecycle method on any of them: it
holds them, and the workflow passes them on.

``require_probe_runner`` was in that group in the draft design and is NOT here.
The per-field audit found it is a plain ``bool`` launch flag read once — it
belongs to :class:`workflows.run_config.WorkflowLaunchConfig`. Keeping it would
have been the "it reduces the signature" reasoning Amendment A exists to
prevent.

There is deliberately no fourth "services" carrier: three unrelated immutable
references are not a coherent boundary, and inventing a container for them would
be a shape, not an owner.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import fields as dataclass_fields
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from agent.schemas.ordering import OrderStrategy
    from core.run_invariants import RunInvariants
    from core.runtime_control.measurement_capability import ResolvedMeasurementCapability
    from execute_tools.dataset_config import DataScope
    from workflows.llm_config import WorkflowLLMConfig


@dataclass(frozen=True, slots=True)
class WorkflowRunBindings:
    """Run-scoped authorities and immutable capability references.

    Constructed once, inside ``run_workflow``, after the startup side effects
    that the derived values depend on (the effective Health config must be
    materialised and hashed before the invariants lock is written). Moving
    construction to the launcher is Step-10/12 work, not this milestone's.
    """

    # --- run identity ---------------------------------------------------------

    #: Chain workspace root.
    workspace: str
    #: This run's name; also the storage naming stem.
    run_name: str
    #: ``{workspace}/{run_name}`` — resolved once so no caller re-derives it.
    run_dir: str
    #: Chain identity bound into every agent, when the launcher supplies one.
    chain_run_name: str | None = None
    run_id: str | None = None

    # --- locked run invariants ------------------------------------------------

    #: The operator's requested scope, before resolution.
    data_scope: DataScope | None = None
    #: The resolved, sorted file indices this run may touch.
    resolved_data_scope: tuple[int, ...] = ()
    #: Whether ``resolved_data_scope`` is narrower than the dataset.
    scope_is_partial: bool = False
    health_gate_enabled: bool = True
    health_gate_files: tuple[int, ...] | None = None
    health_checks_config: str | None = None
    order_strategy_override: OrderStrategy | None = None
    file_order_override: tuple[int, ...] | None = None
    enable_structured_health_feedback: bool = False
    #: The workspace's invariant lock, as built by ``build_run_invariants``.
    run_invariants: RunInvariants | None = None

    # --- resolved run authorities --------------------------------------------

    #: The run's LLM authority, normalised once at entry.
    llm_config: WorkflowLLMConfig | None = None
    #: The metric spec reconciled from the seed tuning outputs.
    seed_metric_spec: Any = None
    #: The resolved hardware context.
    hardware_context: Any = None
    #: The VRAM budget in force, derived from the trial/formal budgets.
    active_vram_budget_gb: float | None = None
    #: The proposer's reasoning pipeline, or ``None`` for legacy 2-call mode.
    reasoning_pipeline: Any = None
    #: The static vocabulary seed.
    vocab_seed: tuple[Any, ...] = ()

    # --- immutable capability references (Amendment A) ------------------------

    bridge_factory: Any = None
    sandbox_factory: Any = None
    measurement_capability: ResolvedMeasurementCapability | None = None

    def __post_init__(self) -> None:
        """Refuse mutable cross-iteration state.

        The forbidden set is DERIVED from :class:`core.chain_state.ChainState`'s
        own fields rather than hand-listed. A maintained-by-hand deny list goes
        stale the first time the state carrier grows — and the field it fails to
        name is exactly the one that would leak.
        """
        from core.chain_state import chain_state_field_names

        offending = sorted(chain_state_field_names() & {f.name for f in dataclass_fields(self)})
        if offending:
            raise TypeError(
                f"WorkflowRunBindings must not carry mutable chain state: {offending}. "
                "Bindings are authorities settled at startup whose identity does not "
                "change; values that evolve as iterations complete belong to ChainState."
            )


def run_bindings_field_names() -> frozenset[str]:
    """The carrier's field names — used by the structural censuses."""
    return frozenset(f.name for f in dataclass_fields(WorkflowRunBindings))
