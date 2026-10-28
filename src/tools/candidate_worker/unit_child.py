"""Known unit child: execute one graph node invocation in its own process (B3-3).

The parent worker already bound the generated library to the workspace; the
binding is inherited through the environment and checked here before any
native task consumer is imported. Process-global registries and the torch
default RNG therefore start fresh for every unit.
"""

import os
import sys
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.generated_library import generated_library_is_workspace_bound, verified_chain_workspace

if TYPE_CHECKING:
    from workflows.task_composition import RunTaskComposition

    from .unit_models import NodeInvocation, NodeOutput


def execute_unit(
    invocation: "NodeInvocation", composition: "RunTaskComposition"
) -> "tuple[NodeOutput, Path]":
    """The native phase call `graph.execute_fanout` made in-process before B3-3.

    Native modules are imported here, after the entry checked the inherited
    generated-library binding (import order is an execution invariant).
    """
    from .invocation import invocation_from_storage
    from .layout import tuning_input_path
    from .unit_models import (
        ImplementationUnit,
        InterpretationUnit,
        LiteratureUnit,
        ProposalUnit,
        TuningUnit,
        ValidationUnit,
    )

    request, initial, config, unit = (
        invocation.request,
        invocation.initial,
        invocation.config,
        invocation.unit,
    )
    context = invocation_from_storage(
        initial,
        node_id=invocation.node_id,
        phase=unit.phase,
        storage=invocation.storage,
        iteration=invocation.iteration,
    )
    if isinstance(unit, TuningUnit):
        from .training import run_training

        context.require_resolved_binding(
            initial,
            run_name=request.run_name,
            node_id=invocation.node_id,
            phase="tuning",
            storage=invocation.storage,
            implementation_directory="",
        )
        return run_training(
            context,
            unit.proposal,
            unit.implementation,
            unit.validation,
            unit.admission.restore(composition, config),
            storage=invocation.storage,
            chain_formal_incumbent_reference=unit.chain_formal_incumbent_reference,
            input_path=tuning_input_path(
                Path(initial.workspace), invocation.node_id, iteration=invocation.iteration
            ),
        )
    if isinstance(unit, InterpretationUnit):
        from .interpretation import run_interpretation

        return run_interpretation(context, initial, unit.inputs, config)
    if isinstance(unit, LiteratureUnit):
        from .literature_phase import run_literature

        return run_literature(context, request, initial, unit.inputs)
    from . import phases

    if isinstance(unit, ProposalUnit):
        return phases.run_proposal(context, request, initial, unit.inputs, config)
    if isinstance(unit, ImplementationUnit):
        return phases.run_implementation(
            context,
            request,
            initial,
            unit.inputs,
            config,
            unit.proposal,
            composition.implementor_blocks,
        )
    assert isinstance(unit, ValidationUnit)
    return phases.run_validation(
        context, request, initial, unit.inputs, config, unit.proposal, unit.implementation
    )


def run_invocation_file(path: Path) -> None:
    """Execute the invocation at `path` and publish its write-once result beside it."""
    from core.durable_io import publish_bytes_write_once
    from core.runtime_control.observed_subprocess import ProcessLifecycle, observe_process_lifecycle
    from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

    from .unit_models import NodeInvocation, NodeUnitResult
    from .unit_transport import decode_transport, encode_transport

    invocation = decode_transport(NodeInvocation, path.read_bytes())
    if os.path.abspath(verified_chain_workspace()) != os.path.abspath(invocation.initial.workspace):
        raise ValueError("unit child workspace binding disagrees with its invocation")

    def finished(**values: Any) -> NodeUnitResult:
        return NodeUnitResult(node_id=invocation.node_id, phase=invocation.unit.phase, **values)

    lifecycles: list[ProcessLifecycle] = []
    with observe_process_lifecycle(lifecycles.append):
        try:
            composition = compose_run_task_bindings(invocation.manifest_path)
            if composition.semantic_fingerprint != invocation.composition_fingerprint:
                raise ValueError("unit child composition disagrees with the dispatching body")
            with bind_run_task_composition(
                composition, physical_data_root=invocation.physical_data_root
            ):
                output, record = execute_unit(invocation, composition)
            result = finished(
                outcome="returned",
                output=encode_transport(output).decode(),
                record_path=str(record),
            )
        except Exception:
            traceback.print_exc()
            result = finished(outcome="raised")
        except SystemExit as error:
            code = error.code
            result = finished(
                outcome="exited",
                exit_code=code if code is None or isinstance(code, (int, str)) else str(code),
            )
        except KeyboardInterrupt:
            result = finished(outcome="interrupted")
    result = result.model_copy(update={"lifecycles": tuple(lifecycles)})
    publish_bytes_write_once(str(path.with_name("result.json")), encode_transport(result))


if __name__ == "__main__":
    # One worker log: stderr joins the inherited stdout (the worker's log file),
    # because the process supervisor pipes stderr.
    os.dup2(1, 2)
    if not generated_library_is_workspace_bound():
        raise SystemExit("unit child requires the worker's workspace generated-library binding")
    run_invocation_file(Path(sys.argv[1]))
