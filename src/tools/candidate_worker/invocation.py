"""Internal fixed-slot invocation identity, independent of scientific candidate IDs."""

from dataclasses import dataclass, field
from typing import Any, Literal

from workflows.definition.candidate import candidate_nodes
from workflows.run_context import bind_agent_run_context

from .inputs import NativeInputs
from .models import CandidateRunReceipt, CandidateRunRequest

NativePhase = Literal["proposal", "implementation", "validation"]


@dataclass(frozen=True)
class FixedInvocationContext:
    """Snapshot of an admitted fixed invocation; never a graph storage namespace.

    Storage values are copied from materialized inputs, not retained as a mutable
    Pydantic object. Node IDs select a declaration identity, never a path or prompt.
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
        node_ids = candidate_nodes(request.preview.document.definition)
        if self.phase != phase or self.node_id != node_ids[phase]:
            raise ValueError("native invocation node/phase binding disagrees")
        if (
            (self.workspace, self.run_id, self.run_name)
            != (initial.workspace, initial.run_id, initial.run_name)
            or self.run_name != request.run_name
            or self.node_id not in initial.node_ids
        ):
            raise ValueError("native invocation run binding disagrees")
        storage = inputs.proposal.storage if phase == "proposal" else inputs.attempt.storage
        if (
            storage.backend != "local"
            or storage.local is None
            or (self.storage_workspace, self.storage_run_name)
            != (storage.local.workspace, storage.local.run_name)
            or self.storage_run_name != self.run_name
            or (phase != "proposal" and self.storage_workspace != inputs.attempt.impl_dir)
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
        storage = inputs.proposal.storage if phase == "proposal" else inputs.attempt.storage
        if storage.local is None:
            raise ValueError("native invocation requires materialized local storage")
        return FixedInvocationContext(
            workspace=initial.workspace,
            run_id=initial.run_id,
            run_name=initial.run_name,
            node_id=node_ids[phase],
            phase=phase,
            storage_workspace=storage.local.workspace,
            storage_run_name=storage.local.run_name,
        )

    return context("proposal"), context("implementation"), context("validation")
