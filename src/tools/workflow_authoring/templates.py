"""Task-agnostic starting shapes for the workflow editor; the one template owner.

A template is a typed reusable (v2) declaration *shape*: capabilities, protocols,
managed external roles, positions and, for loops, the authored feedback with a
finite iteration limit. It names no task, data path, model, advice text or
training value. Instantiation copies the opened project's own task references
and accepted task binding into the shape and renders canonical source; the
editor then reviews that source through the ordinary ``source`` proposal path,
and only an explicit Save publishes it.

Shapes reuse the audited native profiles (``native-interpretation-candidate/v1``
and the plain candidate preview) exactly as the reusable examples under
``examples/workflow_declarations`` and the reusable browser fixtures use them.
A Literature review node is not offered inside a loop: the catalog has no
protocol that joins ``literature.output`` into an interpretation-fed proposal
(B6 adaptor design).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from workflows.definition import (
    ArgumentBinding,
    AuthoredLoop,
    AuthoredWorkflowDocument,
    ExternalRequest,
    ExternalSource,
    LoopFeedback,
    ManagedCandidateBinding,
    NodeInstance,
    NodePosition,
    ProtocolRequest,
    ResultSource,
    ReusableTaskReferences,
    ReusableWorkflowDefinition,
    ReusableWorkflowDocument,
    TaskBinding,
    WorkflowDocument,
    render_workflow_source,
)

TemplateId = Literal["single-research-loop", "single-loop-with-advice", "single-step"]

# Every template contains Train & tune, whose launch policy has no default
# (execute_tools.health_checks.launch_policy). Templates declare it visibly in the
# authored source as blocking Health checks with scientific standing: the task's own
# blocking checks invalidate a round and its recording checks only record (an
# observe-only run is refused at training admission when the task declares blocking
# checks). Scientific standing lets Health-valid results count as the run's
# authoritative score (a diagnostic run excludes every result from it); the author
# may change both in the Train & tune inspector. Templates also
# declare trial/formal mode (``is_trial``), the command line's default: the native
# launch default (false) is single-file mode, which only a TIDMAD-topology task can
# train in (``execute_tools.dataset_config.single_file_mode_refusal``).
DECLARED_LAUNCH_POLICY: dict[str, str | bool] = {
    "healthgate_mode": "blocking",
    "result_authority": "scientific",
    "is_trial": True,
}
# The smallest valid loop bound, as for a one-click added loop (loop.py): an
# imported loop costs no more than one body until the author raises it.
TEMPLATE_FINAL_ITERATION = 1
GRID_X = 320.0


class TemplateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TemplatePreviewNode(TemplateModel):
    id: str
    capability: str
    x: float
    y: float


class TemplatePreviewEdge(TemplateModel):
    source: str
    target: str
    argument: str


class TemplatePreviewLoop(TemplateModel):
    source: str
    target: str
    final_iteration: int


class TemplatePreview(TemplateModel):
    """Thumbnail data derived from the template document, never authored separately."""

    nodes: tuple[TemplatePreviewNode, ...]
    edges: tuple[TemplatePreviewEdge, ...]
    loop: TemplatePreviewLoop | None = None


class WorkflowTemplate(TemplateModel):
    id: TemplateId
    title: str
    description: str
    preview: TemplatePreview


class TemplateCatalog(TemplateModel):
    templates: tuple[WorkflowTemplate, ...]


class TemplateImportRequest(TemplateModel):
    template_id: TemplateId
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class TemplateImportView(TemplateModel):
    """Unsaved candidate source; the editor reviews it as an ordinary source proposal."""

    template_id: TemplateId
    source: str


class TemplateRefusal(ValueError):
    """The opened source cannot supply task references for a template."""


# Placeholder task references; instantiation always replaces them with the
# opened project's own references, so they never reach a reviewed source.
_SHAPE_TASK = ReusableTaskReferences(manifest="task.yaml", data_root="data")


def _external(binding: str) -> ExternalSource:
    return ExternalSource(binding=binding)


def _protocol(node: str, capability: str, protocol: str, **arguments: str) -> NodeInstance:
    """Arguments name a result node or, with an ``@`` prefix, a managed external."""
    return NodeInstance(
        id=node,
        capability=capability,
        request=ProtocolRequest(
            protocol=protocol,
            arguments=tuple(
                ArgumentBinding(
                    name=name,
                    source=_external(value[1:])
                    if value.startswith("@")
                    else ResultSource(node=value),
                )
                for name, value in arguments.items()
            ),
        ),
    )


def _managed(*pairs: tuple[str, str]) -> tuple[ManagedCandidateBinding, ...]:
    return tuple(
        ManagedCandidateBinding.model_validate({"id": name, "contract": contract})
        for name, contract in pairs
    )


def _positions(*nodes: str) -> tuple[NodePosition, ...]:
    return tuple(
        NodePosition(node=node, x=index * GRID_X, y=0.0) for index, node in enumerate(nodes)
    )


def _candidate_tail(proposal: str) -> tuple[NodeInstance, ...]:
    """Implementation → validation → train & tune for one proposal (native join edges)."""
    return (
        _protocol(
            "implement",
            "implementation",
            "proposal-to-implementation",
            output=proposal,
            storage="@implement_store",
        ),
        _protocol(
            "validate",
            "validation",
            "proposed-implementation-to-validation",
            proposal=proposal,
            implementation="implement",
            storage="@validate_store",
        ),
        _protocol(
            "train",
            "tuning",
            "validated-candidate-to-tuning",
            proposal=proposal,
            validation="validate",
            settings="@training",
        ),
    )


def _research_loop(with_advice: bool) -> ReusableWorkflowDocument:
    """Interpretation → proposal → implementation → validation → train & tune, fed back."""
    advisory = {"human_advice": "@advice", "expert_context": "@findings"} if with_advice else {}
    proposal = _protocol(
        "propose",
        "proposal",
        "interpretation-to-proposal",
        output="interpret",
        storage="@propose_store",
        data_dir="@data_dir",
        task_composition_ref="@task_ref",
        **advisory,
        constraint_context="@constraints",
        workflow_parameter_rules="@rules",
    )
    externals = _managed(
        ("evidence", "interpretation.input"),
        ("propose_store", "storage"),
        ("data_dir", "optional.text"),
        ("task_ref", "optional.task-composition-ref"),
        *(
            (("advice", "optional.expert-advice"), ("findings", "optional.expert-context"))
            if with_advice
            else ()
        ),
        ("constraints", "optional.constraint-context"),
        ("rules", "optional.parameter-rules"),
        ("implement_store", "storage"),
        ("validate_store", "storage"),
        ("training", "native-training.settings"),
    )
    return ReusableWorkflowDocument(
        definition=ReusableWorkflowDefinition(
            task=_SHAPE_TASK,
            externals=externals,
            nodes=(
                NodeInstance(
                    id="interpret",
                    capability="interpretation",
                    request=ExternalRequest(binding="evidence"),
                ),
                proposal,
                *_candidate_tail("propose"),
            ),
            loop=AuthoredLoop(
                final_iteration=TEMPLATE_FINAL_ITERATION,
                feedback=LoopFeedback(
                    source=ResultSource(node="train"),
                    target="interpret",
                    protocol="tuning-to-interpretation",
                    history="native-research/v1",
                ),
            ),
        ),
        positions=_positions("interpret", "propose", "implement", "validate", "train"),
        execution_profile="native-interpretation-candidate/v1",
        # Native launch defaults apply until the author edits a training control; only the
        # launch policy pair is declared, because training admission has no default for it.
        training_settings={"launch": dict(DECLARED_LAUNCH_POLICY)},
    )


def _single_step() -> ReusableWorkflowDocument:
    """One proposal → implementation → validation → train & tune body, no feedback."""
    return ReusableWorkflowDocument(
        definition=ReusableWorkflowDefinition(
            task=_SHAPE_TASK,
            externals=_managed(
                ("initial", "proposal.input"),
                ("implement_store", "storage"),
                ("validate_store", "storage"),
                ("training", "native-training.settings"),
            ),
            nodes=(
                NodeInstance(
                    id="propose", capability="proposal", request=ExternalRequest(binding="initial")
                ),
                _protocol(
                    "implement",
                    "implementation",
                    "proposal-to-implementation",
                    output="propose",
                    storage="@implement_store",
                ),
                _protocol(
                    "validate",
                    "validation",
                    "implementation-to-validation",
                    output="implement",
                    storage="@validate_store",
                ),
                _protocol(
                    "train",
                    "tuning",
                    "validated-candidate-to-tuning",
                    proposal="propose",
                    validation="validate",
                    settings="@training",
                ),
            ),
        ),
        positions=_positions("propose", "implement", "validate", "train"),
        training_settings={"launch": dict(DECLARED_LAUNCH_POLICY)},
    )


_SHAPES: tuple[tuple[TemplateId, str, str, ReusableWorkflowDocument], ...] = (
    (
        "single-research-loop",
        "Single research loop",
        "Interpret results, propose, implement, validate, train & tune, then feed back. "
        "The first round starts cold: no earlier results are needed.",
        _research_loop(with_advice=False),
    ),
    (
        "single-loop-with-advice",
        "Single loop with your own advice",
        "The same loop; the proposal agent also reads your advice. "
        "The first round starts cold: no earlier results are needed.",
        _research_loop(with_advice=True),
    ),
    (
        "single-step",
        "Single step (no loop)",
        "Propose, implement, validate and train & tune one candidate once.",
        _single_step(),
    ),
)


def preview(document: ReusableWorkflowDocument) -> TemplatePreview:
    positions = {item.node: item for item in document.positions}
    edges = tuple(
        TemplatePreviewEdge(source=argument.source.node, target=node.id, argument=argument.name)
        for node in document.definition.nodes
        if isinstance(node.request, ProtocolRequest)
        for argument in node.request.arguments
        if isinstance(argument.source, ResultSource)
    )
    loop = document.definition.loop
    return TemplatePreview(
        nodes=tuple(
            TemplatePreviewNode(
                id=node.id,
                capability=node.capability,
                x=positions[node.id].x,
                y=positions[node.id].y,
            )
            for node in document.definition.nodes
        ),
        edges=edges,
        loop=TemplatePreviewLoop(
            source=loop.feedback.source.node,
            target=loop.feedback.target,
            final_iteration=loop.final_iteration,
        )
        if loop is not None
        else None,
    )


def template_catalog() -> TemplateCatalog:
    return TemplateCatalog(
        templates=tuple(
            WorkflowTemplate(id=key, title=title, description=text, preview=preview(document))
            for key, title, text, document in _SHAPES
        )
    )


def template_document(template_id: TemplateId) -> ReusableWorkflowDocument:
    return next(document for key, _, _, document in _SHAPES if key == template_id)


def blank_document() -> ReusableWorkflowDocument:
    """The smallest valid reusable shape: one Propose node fed by its managed input.

    A declaration needs at least one node, so a "blank" experiment setup starts
    from the first node every template shares and nothing else.
    """
    return ReusableWorkflowDocument(
        definition=ReusableWorkflowDefinition(
            task=_SHAPE_TASK,
            externals=_managed(("initial", "proposal.input")),
            nodes=(
                NodeInstance(
                    id="propose", capability="proposal", request=ExternalRequest(binding="initial")
                ),
            ),
        ),
        positions=_positions("propose"),
    )


def render_shape(
    template_id: TemplateId | None,
    references: ReusableTaskReferences,
    binding: TaskBinding | None = None,
) -> str:
    """Render a template (``None``: the blank shape) with explicit task references.

    The caller owns the references and the accepted binding; the shape never
    chooses a task or data location.
    """
    shape = blank_document() if template_id is None else template_document(template_id)
    document = shape.model_copy(
        update={
            "definition": shape.definition.model_copy(update={"task": references}),
            "task_binding": binding,
        }
    )
    return render_workflow_source(document)


def instantiate(template_id: TemplateId, current: AuthoredWorkflowDocument | None) -> str:
    """Render the template with the opened project's own task references and binding.

    The template never chooses a task or data location: an unparsed current
    source has none to copy and is refused. A v1 source contributes its manifest
    and data root; a reusable source also keeps its accepted ``task_binding``,
    which the ordinary bound-review path then requires the author to select.
    """
    if current is None:
        raise TemplateRefusal("open a supported workflow source before importing a template")
    task = current.definition.task
    binding: TaskBinding | None = None
    if isinstance(current, WorkflowDocument):
        references = ReusableTaskReferences(manifest=task.manifest, data_root=task.data_root)
    else:
        references = ReusableTaskReferences.model_validate(task.model_dump())
        binding = current.task_binding
    return render_shape(template_id, references, binding)
