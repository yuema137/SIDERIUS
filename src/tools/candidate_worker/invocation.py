"""Native invocation identity, independent of scientific candidate IDs."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from agent.schemas.storage import StorageConfig
from workflows.definition.candidate import candidate_nodes
from workflows.run_context import bind_agent_run_context

from .inputs import NativeInputs
from .models import CandidateRunReceipt, CandidateRunRequest

NativePhase = Literal["proposal", "implementation", "validation"]


@dataclass(frozen=True)
class FixedInvocationContext:
    """Snapshot of an admitted fixed or explicitly declared instance invocation.

    Storage values are copied from materialized inputs, not retained as a mutable
    Pydantic object. Admission derives managed slots from declaration identities.
    The existing candidate worker exposes only iteration 1 and attempt 1.
    """

    workspace: str
    run_id: str
    run_name: str
    node_id: str
    phase: NativePhase
    storage_workspace: str
    storage_run_name: str
    iteration: Literal[1] = field(default=1, init=False)
    attempt: Literal[1] = field(default=1, init=False)

    def require_binding(
        self,
        request: CandidateRunRequest,
        initial: CandidateRunReceipt,
        inputs: NativeInputs,
        phase: NativePhase,
    ) -> None:
        """Refuse a lost or swapped invocation before node construction/effects.

        This compares invocation bindings only. Materialize retains scientific
        and external-input reconciliation; candidate_nodes retains shape checks.
        """
        if request.preview.execution_profile is not None:
            from workflows.attempt_storage import impl_attempt_storage
            from workflows.definition.fanout import proposal_fanout

            from .layout import graph_instance_dir

            definition = request.preview.document.definition
            shape = proposal_fanout(definition)
            node = next((node for node in definition.nodes if node.id == self.node_id), None)
            if node is None or node.capability != phase:
                raise ValueError("native invocation node/phase binding disagrees")
            parent = dict((validation, impl) for impl, validation in shape.branches)
            owner = parent.get(self.node_id, self.node_id)
            directory = graph_instance_dir(Path(initial.workspace), request.run_name, owner)
            expected = (
                str(directory)
                if phase == "proposal"
                else impl_attempt_storage(str(directory), request.run_name, 1).impl_dir
            )
            if self.storage_workspace != expected:
                raise ValueError("native invocation storage binding disagrees")
            node_ids = {phase: self.node_id}
        else:
            node_ids = candidate_nodes(request.preview.document.definition)
        self.require_resolved_binding(
            initial,
            run_name=request.run_name,
            node_id=node_ids[phase],
            phase=phase,
            storage=inputs.proposal.storage if phase == "proposal" else inputs.attempt.storage,
            implementation_directory=inputs.attempt.impl_dir,
        )

    def require_resolved_binding(
        self,
        initial: CandidateRunReceipt,
        *,
        run_name: str,
        node_id: str,
        phase: NativePhase,
        storage: StorageConfig,
        implementation_directory: str,
    ) -> None:
        """Compare explicit selected bindings without rediscovering a topology."""
        if self.phase != phase or self.node_id != node_id:
            raise ValueError("native invocation node/phase binding disagrees")
        if (
            (self.workspace, self.run_id, self.run_name)
            != (initial.workspace, initial.run_id, initial.run_name)
            or self.run_name != run_name
            or self.node_id not in initial.node_ids
        ):
            raise ValueError("native invocation run binding disagrees")
        if (
            storage.backend != "local"
            or storage.local is None
            or (self.storage_workspace, self.storage_run_name)
            != (storage.local.workspace, storage.local.run_name)
            or self.storage_run_name != self.run_name
            or (phase != "proposal" and self.storage_workspace != implementation_directory)
        ):
            raise ValueError("native invocation storage binding disagrees")

    def bind(self, agent: Any) -> None:
        """Bind the existing native accounting context using the checked identity."""
        bind_agent_run_context(
            agent,
            workspace=self.workspace,
            iteration=self.iteration,
            run_name=self.run_name,
            run_id=self.run_id,
        )


def fixed_invocations(
    request: CandidateRunRequest, initial: CandidateRunReceipt, inputs: NativeInputs
) -> tuple[FixedInvocationContext, FixedInvocationContext, FixedInvocationContext]:
    """Use the single candidate shape owner and the existing materialized slots."""
    node_ids = candidate_nodes(request.preview.document.definition)

    def context(phase: NativePhase) -> FixedInvocationContext:
        return invocation_from_storage(
            initial,
            node_id=node_ids[phase],
            phase=phase,
            storage=inputs.proposal.storage if phase == "proposal" else inputs.attempt.storage,
        )

    return context("proposal"), context("implementation"), context("validation")


def invocation_from_storage(
    initial: CandidateRunReceipt,
    *,
    node_id: str,
    phase: NativePhase,
    storage: StorageConfig,
) -> FixedInvocationContext:
    """Snapshot selected native storage; fixed_invocations owns fixed selection."""
    if storage.local is None:
        raise ValueError("native invocation requires materialized local storage")
    return FixedInvocationContext(
        workspace=initial.workspace,
        run_id=initial.run_id,
        run_name=initial.run_name,
        node_id=node_id,
        phase=phase,
        storage_workspace=storage.local.workspace,
        storage_run_name=storage.local.run_name,
    )
