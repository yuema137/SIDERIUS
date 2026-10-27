"""Research-loop addition template; `AuthoredLoop` and its validator stay authoritative."""

from workflows.definition import (
    AuthoredLoop,
    AuthoredWorkflowDocument,
    LoopFeedback,
    ResultSource,
    parse_workflow_source,
)

# The smallest valid bound: an added loop costs no more than one body until the
# author explicitly raises it. Review/Save validate every submitted value.
ADDED_LOOP_FINAL_ITERATION = 1


def loop_template(document: AuthoredWorkflowDocument) -> AuthoredLoop | None:
    """Return the one supported feedback edge an editor may add, else ``None``.

    The declaration supports exactly one tuning→interpretation feedback. A graph
    with several tuning or interpretation nodes is ambiguous for a one-click
    addition, so its feedback stays source-authored. The template is inert: it
    is never published unless the author submits it through Review and Save.
    """
    nodes = document.definition.nodes
    tuning = [node.id for node in nodes if node.capability == "tuning"]
    interpretation = [node.id for node in nodes if node.capability == "interpretation"]
    if len(tuning) != 1 or len(interpretation) != 1:
        return None
    return AuthoredLoop(
        final_iteration=ADDED_LOOP_FINAL_ITERATION,
        feedback=LoopFeedback(
            source=ResultSource(node=tuning[0]),
            target=interpretation[0],
            protocol="tuning-to-interpretation",
            history="native-research/v1",
        ),
    )


def with_loop(source: str, loop: AuthoredLoop | None) -> AuthoredWorkflowDocument:
    """Parse one complete declaration and replace only its authored loop.

    The caller renders the result, which revalidates the loop endpoints through
    the declaration validator exactly as a code-authored edit would.
    """
    document = parse_workflow_source(source)
    definition = document.definition.model_copy(update={"loop": loop})
    return document.model_copy(update={"definition": definition})
