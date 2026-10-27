"""Static translation witnesses; expected source/models are independently authored."""

import ast
import subprocess
import sys

import pytest

from workflows.definition import (
    ArgumentBinding,
    ExternalBinding,
    ExternalRequest,
    ExternalSource,
    NodeInstance,
    NodePosition,
    ProtocolRequest,
    ResultSource,
    TaskReferences,
    WorkflowDefinition,
    WorkflowDocument,
    WorkflowSourceError,
    parse_workflow_source,
    render_workflow_source,
)
from workflows.definition import source as bridge

SMALL_SOURCE = """from workflows.definition import (
    WorkflowDocument, WorkflowDefinition, TaskReferences,
    ExternalBinding, NodeInstance, ExternalRequest,
)
document = WorkflowDocument(definition=WorkflowDefinition(
    task=TaskReferences(manifest="task.json", data_root="missing/data", workspace="missing/run"),
    externals=(ExternalBinding(id="seed", contract="proposal.input", location="missing/plugin.py"),),
    nodes=(NodeInstance(id="p", capability="proposal", request=ExternalRequest(binding="seed")),),
))
"""

GOLDEN = """# Generated workflow declaration; comments and formatting are not preserved.
from workflows.definition import (
    TaskReferences,
    ExternalBinding,
    ExternalSource,
    ResultSource,
    ArgumentBinding,
    ExternalRequest,
    ProtocolRequest,
    NodeInstance,
    WorkflowDefinition,
    NodePosition,
    WorkflowDocument,
)

document = WorkflowDocument(
    definition=WorkflowDefinition(
        schema_version=1,
        task=TaskReferences(
            manifest='task.json',
            data_root='missing/data',
            workspace='missing/run',
        ),
        externals=(
            ExternalBinding(
                id='seed',
                contract='proposal.input',
                location='missing/plugin.py',
            ),
        ),
        nodes=(
            NodeInstance(
                id='p',
                capability='proposal',
                request=ExternalRequest(
                    kind='external',
                    binding='seed',
                ),
            ),
        ),
    ),
    positions=(),
)
"""

CHAIN_SOURCE = '''"""An inert dedicated module."""
from workflows.definition import (
    TaskReferences, ExternalBinding, ExternalSource, ResultSource,
    ArgumentBinding, ExternalRequest, ProtocolRequest, NodeInstance,
    WorkflowDefinition, NodePosition, WorkflowDocument,
)
# Both protocols, deliberately non-default argument order and explicit context.
document = WorkflowDocument(
    definition=WorkflowDefinition(
        schema_version=+1,
        task=TaskReferences(manifest="任务/manifest.json", data_root="/missing/data", workspace="runs/新"),
        externals=(
            ExternalBinding(id="seed", contract="proposal.input", location="inputs/seed.json"),
            ExternalBinding(id="storage", contract="storage", location="inputs/存储\\n.json"),
            ExternalBinding(id="context", contract="optional.constraint-context", location="context.json"),
            ExternalBinding(id="model", contract="optional.model-id", location="model.json"),
        ),
        nodes=(
            NodeInstance(id="p", capability="proposal", request=ExternalRequest(binding="seed")),
            NodeInstance(id="i", capability="implementation", request=ProtocolRequest(
                protocol="proposal-to-implementation", arguments=(
                    ArgumentBinding(name="storage", source=ExternalSource(binding="storage")),
                    ArgumentBinding(name="output", source=ResultSource(node="p")),
                    ArgumentBinding(name="constraint_context", source=ExternalSource(binding="context")),
                ),
            )),
            NodeInstance(id="v", capability="validation", request=ProtocolRequest(
                protocol="implementation-to-validation", arguments=(
                    ArgumentBinding(name="output", source=ResultSource(node="i")),
                    ArgumentBinding(name="storage", source=ExternalSource(binding="storage")),
                    ArgumentBinding(name="llm_model_id", source=ExternalSource(binding="model")),
                ),
            )),
        ),
    ),
    positions=(NodePosition(node="v", x=-2.5, y=+3.0), NodePosition(node="p", x=0.0, y=-0.0)),
)
'''


def small_document():
    return WorkflowDocument(
        definition=WorkflowDefinition(
            task=TaskReferences(
                manifest="task.json", data_root="missing/data", workspace="missing/run"
            ),
            externals=(
                ExternalBinding(id="seed", contract="proposal.input", location="missing/plugin.py"),
            ),
            nodes=(
                NodeInstance(
                    id="p", capability="proposal", request=ExternalRequest(binding="seed")
                ),
            ),
        )
    )


def test_handwritten_chain_preserves_complete_models_and_order():
    """Dropped bindings, reordered arguments or rebased/escaped paths break equality."""
    expected = WorkflowDocument(
        definition=WorkflowDefinition(
            task=TaskReferences(
                manifest="任务/manifest.json", data_root="/missing/data", workspace="runs/新"
            ),
            externals=(
                ExternalBinding(id="seed", contract="proposal.input", location="inputs/seed.json"),
                ExternalBinding(id="storage", contract="storage", location="inputs/存储\n.json"),
                ExternalBinding(
                    id="context", contract="optional.constraint-context", location="context.json"
                ),
                ExternalBinding(id="model", contract="optional.model-id", location="model.json"),
            ),
            nodes=(
                NodeInstance(
                    id="p", capability="proposal", request=ExternalRequest(binding="seed")
                ),
                NodeInstance(
                    id="i",
                    capability="implementation",
                    request=ProtocolRequest(
                        protocol="proposal-to-implementation",
                        arguments=(
                            ArgumentBinding(
                                name="storage", source=ExternalSource(binding="storage")
                            ),
                            ArgumentBinding(name="output", source=ResultSource(node="p")),
                            ArgumentBinding(
                                name="constraint_context", source=ExternalSource(binding="context")
                            ),
                        ),
                    ),
                ),
                NodeInstance(
                    id="v",
                    capability="validation",
                    request=ProtocolRequest(
                        protocol="implementation-to-validation",
                        arguments=(
                            ArgumentBinding(name="output", source=ResultSource(node="i")),
                            ArgumentBinding(
                                name="storage", source=ExternalSource(binding="storage")
                            ),
                            ArgumentBinding(
                                name="llm_model_id", source=ExternalSource(binding="model")
                            ),
                        ),
                    ),
                ),
            ),
        ),
        positions=(NodePosition(node="v", x=-2.5, y=3.0), NodePosition(node="p", x=0.0, y=-0.0)),
    )
    parsed = parse_workflow_source(CHAIN_SOURCE)
    assert parsed == expected
    rendered = render_workflow_source(parsed)
    assert parse_workflow_source(rendered) == expected
    assert render_workflow_source(parse_workflow_source(rendered)) == rendered
    # Optional native defaults must never become new declared protocol arguments.
    assert tuple(arg.name for arg in parsed.definition.nodes[2].request.arguments) == (
        "output",
        "storage",
        "llm_model_id",
    )
    moved = parsed.model_copy(update={"positions": (NodePosition(node="v", x=500.0, y=-20.0),)})
    assert parse_workflow_source(render_workflow_source(moved)).definition.declaration_digest() == (
        expected.definition.declaration_digest()
    )


def test_independent_golden_pins_imports_defaults_tuples_and_final_newline():
    """A serializer format/default regression fails the handwritten golden assertion."""
    assert parse_workflow_source(SMALL_SOURCE) == small_document()
    assert render_workflow_source(small_document()) == GOLDEN
    assert render_workflow_source(parse_workflow_source(GOLDEN)) == GOLDEN


@pytest.mark.parametrize(
    "source",
    [
        SMALL_SOURCE.replace("from workflows.definition", "from foreign"),
        SMALL_SOURCE.replace("from workflows.definition", "from .workflows.definition"),
        SMALL_SOURCE.replace("WorkflowDocument,", "WorkflowDocument as W,"),
        "from workflows.definition import *\n" + SMALL_SOURCE[SMALL_SOURCE.index("document =") :],
        SMALL_SOURCE.replace("WorkflowDocument,", "WorkflowDocument, WorkflowDocument,"),
        SMALL_SOURCE.replace("ExternalRequest,", ""),
        SMALL_SOURCE.replace("ExternalRequest(binding=", "unknown(binding="),
        SMALL_SOURCE.replace("ExternalRequest(binding=", "module.ExternalRequest(binding="),
        "import sentinel\n" + SMALL_SOURCE,
        SMALL_SOURCE + "print('side effect')\n",
        SMALL_SOURCE.replace("document =", "other ="),
        SMALL_SOURCE.replace("document =", "document = other ="),
        SMALL_SOURCE.replace("document =", "document: object ="),
        SMALL_SOURCE.replace("document = WorkflowDocument(", "document = WorkflowDefinition("),
        SMALL_SOURCE.replace('binding="seed"', '"seed"'),
        SMALL_SOURCE.replace('binding="seed"', "*()"),
        SMALL_SOURCE.replace('binding="seed"', "**{}"),
        SMALL_SOURCE.replace('binding="seed"', 'binding="seed", binding="seed"'),
        SMALL_SOURCE.replace('binding="seed"', 'unknown="seed"'),
        SMALL_SOURCE.replace('binding="seed"', "binding=seed"),
        SMALL_SOURCE.replace('binding="seed"', 'binding=["seed"]'),
        SMALL_SOURCE.replace('binding="seed"', 'binding={"seed": 1}'),
        SMALL_SOURCE.replace('binding="seed"', 'binding={"seed"}'),
        SMALL_SOURCE.replace('binding="seed"', "binding=(x for x in ())"),
        SMALL_SOURCE.replace('binding="seed"', "binding=[x for x in ()]"),
        SMALL_SOURCE.replace('binding="seed"', 'binding=f"seed"'),
        SMALL_SOURCE.replace('binding="seed"', 'binding="se" + "ed"'),
        SMALL_SOURCE.replace('binding="seed"', 'binding=b"seed"'),
        SMALL_SOURCE.replace('binding="seed"', "binding=1j"),
        SMALL_SOURCE.replace('binding="seed"', "binding=..."),
        SMALL_SOURCE.replace('binding="seed"', "binding=--1"),
        SMALL_SOURCE.replace('binding="seed"', "binding=-True"),
        SMALL_SOURCE.replace('binding="seed"', "binding=(None, *())"),
    ],
)
def test_unsupported_syntax_refuses_without_a_partial_document(source):
    """One witness per grammar decision prevents acceptance through fallthrough."""
    with pytest.raises(WorkflowSourceError) as caught:
        parse_workflow_source(source)
    assert caught.value.diagnostics[0].code == "unsupported"


@pytest.mark.parametrize("placement", ["before", "after", "keyword"])
def test_malicious_source_is_inert_and_unchanged(tmp_path, placement):
    """Executing any selected source would create marker; parsing must never do so."""
    marker = tmp_path / "marker"
    effect = f"__import__('pathlib').Path({str(marker)!r}).write_text('executed')"
    source = {
        "before": effect + "\n" + SMALL_SOURCE,
        "after": SMALL_SOURCE + effect + "\n",
        "keyword": SMALL_SOURCE.replace('binding="seed"', f"binding={effect}"),
    }[placement]
    selected = tmp_path / "selected.py"
    selected.write_text(source)
    with pytest.raises(WorkflowSourceError):
        parse_workflow_source(selected.read_text())
    assert not marker.exists()
    assert selected.read_text() == source


def test_cold_import_and_parse_do_not_load_user_plugin_or_runtime(tmp_path):
    """Cold-process imports expose accidental runtime or selected-module loading."""
    selected = tmp_path / "selected_user.py"
    selected.write_text(SMALL_SOURCE)
    (tmp_path / "sentinel_plugin.py").write_text("raise AssertionError('plugin imported')")
    program = """
import pathlib, sys
from workflows.definition import parse_workflow_source, render_workflow_source
render_workflow_source(parse_workflow_source(pathlib.Path(sys.argv[1]).read_text()))
assert not any(n.startswith(('agent.', 'nodes.', 'torch', 'selected_user', 'sentinel_plugin'))
               and n not in {'agent.schemas', 'agent.schemas.output_types'} for n in sys.modules)
"""
    subprocess.run([sys.executable, "-c", program, str(selected)], cwd=tmp_path, check=True)


def test_native_validation_and_unchecked_export_are_reachable_without_value_leaks(recwarn):
    """Bypassed validation accepts broken binding/layout; raw messages leak sentinel."""
    invalid = SMALL_SOURCE.replace('binding="seed"', 'binding="SENTINEL_PRIVATE"')
    with pytest.raises(WorkflowSourceError) as caught:
        parse_workflow_source(invalid)
    diagnostic = caught.value.diagnostics[0]
    assert diagnostic.code == "validation"
    assert diagnostic.line == 5  # WorkflowDefinition owns connection validation.
    assert "SENTINEL_PRIVATE" not in str(caught.value)
    assert "SENTINEL_PRIVATE" not in diagnostic.model_dump_json()
    corrupted = small_document().model_copy(
        update={
            "positions": (NodePosition(node="SENTINEL_PRIVATE", x=0.0, y=0.0),),
        }
    )
    with pytest.raises(WorkflowSourceError) as caught:
        render_workflow_source(corrupted)
    assert caught.value.diagnostics[0].code == "validation"
    assert "SENTINEL_PRIVATE" not in str(caught.value)
    corrupted = small_document().model_copy(
        update={
            "definition": small_document().definition.model_copy(
                update={"schema_version": "PRIVATE"}
            ),
        }
    )
    with pytest.raises(WorkflowSourceError):
        render_workflow_source(corrupted)
    assert not recwarn.list  # Pydantic's default warning includes the unchecked value.


def test_input_size_is_utf8_bytes_and_exact_boundary_is_admitted():
    """Missing byte admission lets a valid oversized source through before AST limits."""
    prefix = SMALL_SOURCE + "#"
    exact = prefix + "é" * ((bridge.MAX_INPUT_BYTES - len(prefix.encode())) // 2)
    exact += " " * (bridge.MAX_INPUT_BYTES - len(exact.encode()))
    assert parse_workflow_source(exact) == small_document()
    with pytest.raises(WorkflowSourceError) as caught:
        parse_workflow_source(exact + "é")
    assert caught.value.diagnostics[0].code == "limit"
    assert caught.value.diagnostics[0].line is None


def test_ast_node_budget_exact_boundary_and_excess(monkeypatch):
    """Resource-count guard is independent of byte and depth admission."""
    count = sum(1 for _ in ast.walk(ast.parse(SMALL_SOURCE)))
    monkeypatch.setattr(bridge, "MAX_AST_NODES", count)
    assert parse_workflow_source(SMALL_SOURCE) == small_document()
    monkeypatch.setattr(bridge, "MAX_AST_NODES", count - 1)
    with pytest.raises(WorkflowSourceError) as caught:
        parse_workflow_source(SMALL_SOURCE)
    assert caught.value.diagnostics[0].code == "limit"
    assert "node" in str(caught.value)


def test_ast_depth_budget_exact_boundary_and_excess(monkeypatch):
    """Iterative depth admission precedes recursive conversion; dropping it fails."""
    pending = [(ast.parse(SMALL_SOURCE), 1)]
    deepest = 0
    while pending:
        node, depth = pending.pop()
        deepest = max(deepest, depth)
        pending.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
    monkeypatch.setattr(bridge, "MAX_AST_DEPTH", deepest)
    assert parse_workflow_source(SMALL_SOURCE) == small_document()
    monkeypatch.setattr(bridge, "MAX_AST_DEPTH", deepest - 1)
    with pytest.raises(WorkflowSourceError) as caught:
        parse_workflow_source(SMALL_SOURCE)
    assert caught.value.diagnostics[0].code == "limit"
    assert "depth" in str(caught.value)


@pytest.mark.parametrize(
    "literal,code", [("1e999", "validation"), ("(" * 300, "syntax"), ("9" * 5000, "syntax")]
)
def test_parser_and_numeric_failures_are_normalized(literal, code):
    """Overflow and parser limits must stay in bridge errors, never uncaught errors."""
    with pytest.raises(WorkflowSourceError) as caught:
        parse_workflow_source(SMALL_SOURCE.replace('binding="seed"', f"binding={literal}"))
    assert caught.value.diagnostics[0].code == code


@pytest.mark.parametrize("character", ["é", "\u2028", "\u0085"])
@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_unicode_spans_use_utf8_byte_columns(character, newline):
    """AST and SyntaxError use different offsets; both normalize to byte columns."""
    unsupported = SMALL_SOURCE.replace('binding="seed"', f'binding=("{character}", unknown)')
    line = unsupported.split("\n")[7]
    with pytest.raises(WorkflowSourceError) as caught:
        parse_workflow_source(unsupported.replace("\n", newline))
    diagnostic = caught.value.diagnostics[0]
    assert (diagnostic.line, diagnostic.column, diagnostic.end_column) == (
        8,
        len(line[: line.index("unknown")].encode()),
        len(line[: line.index("unknown") + 7].encode()),
    )
    broken = SMALL_SOURCE.replace('binding="seed"', f'binding=("{character}" $)')
    line = broken.split("\n")[7]
    with pytest.raises(WorkflowSourceError) as caught:
        parse_workflow_source(broken.replace("\n", newline))
    diagnostic = caught.value.diagnostics[0]
    assert diagnostic.code == "syntax"
    assert (diagnostic.line, diagnostic.column) == (8, len(line[: line.index("$")].encode()))


def test_generated_source_must_satisfy_same_admission_limits(monkeypatch):
    """Without renderer verification an otherwise valid model bypasses bridge budgets."""
    monkeypatch.setattr(bridge, "MAX_INPUT_BYTES", len(GOLDEN.encode()) - 1)
    with pytest.raises(WorkflowSourceError) as caught:
        render_workflow_source(small_document())
    assert caught.value.diagnostics[0].code == "limit"


def test_bound_source_roundtrip_is_inert_in_fresh_process(tmp_path):
    """Pin constructor must not resolve missing task resources or import their owner."""
    from tests.unit.workflows.reusable_fixture import reusable
    from workflows.definition import TaskBinding

    pin = TaskBinding(
        package_id="synthetic",
        revision="local-1",
        task_data_path_id="synthetic_path",
        semantic_fingerprint="a" * 64,
    )
    document = reusable().model_copy(update={"task_binding": pin})
    source = render_workflow_source(document)
    assert parse_workflow_source(source) == document
    assert "TaskBinding(" in source and "task_binding=" in source
    assert document.declaration_digest() != reusable().declaration_digest()
    path = tmp_path / "workflow.py"
    path.write_text(source)
    code = """
import builtins, pathlib, sys
real_import = builtins.__import__
def inert(name, *args, **kwargs):
    if name in {'workflows.task_composition', 'tools.setup_review.composition_child'}:
        raise AssertionError('inert source composed task')
    return real_import(name, *args, **kwargs)
builtins.__import__ = inert
from workflows.definition import parse_workflow_source, render_workflow_source
source = pathlib.Path(sys.argv[1]).read_text()
assert render_workflow_source(parse_workflow_source(source)) == source
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(path)], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def loop_document(*conditions):
    from workflows.definition import AuthoredLoop, LoopFeedback

    return WorkflowDocument(
        definition=WorkflowDefinition(
            task=TaskReferences(manifest="task.json", data_root="data", workspace="run"),
            externals=(
                ExternalBinding(id="seed", contract="interpretation.input", location="seed.json"),
                ExternalBinding(id="tune", contract="tuning.input", location="tune.json"),
            ),
            nodes=(
                NodeInstance(
                    id="interpret",
                    capability="interpretation",
                    request=ExternalRequest(binding="seed"),
                ),
                NodeInstance(
                    id="train", capability="tuning", request=ExternalRequest(binding="tune")
                ),
            ),
            loop=AuthoredLoop(
                final_iteration=3,
                feedback=LoopFeedback(
                    source=ResultSource(node="train"),
                    target="interpret",
                    protocol="tuning-to-interpretation",
                    history="native-research/v1",
                ),
                stop_conditions=conditions,
            ),
        )
    )


def test_loop_without_stop_conditions_keeps_pre_stop_source_bytes_and_digest():
    import hashlib

    document = loop_document()
    source = render_workflow_source(document)
    # Pinned on the pre-stop-condition base f4b633ed: an always-rendered field, a new
    # constructor import or a dumped empty tuple would change existing declarations.
    assert hashlib.sha256(source.encode()).hexdigest() == (
        "f564feba0de613c2c6480741a384cf14e84b392e7975598853b3cb2ad26204e6"
    )
    assert document.definition.declaration_digest() == (
        "0a14c34c8578cab5a8c49f0fe63bc78620a95686d2e9d98df9c39d95a3d86d85"
    )


def test_stop_conditions_roundtrip_and_refuse_judge_duplicates_and_unreachable_k():
    from pydantic import ValidationError

    from workflows.definition import JudgeStop, MetricThresholdStop, NoImprovementStop

    threshold = MetricThresholdStop(metric_id="accuracy", threshold=-0.5)
    document = loop_document(threshold, NoImprovementStop(completed_bodies=2))
    source = render_workflow_source(document)
    assert parse_workflow_source(source) == document
    assert "MetricThresholdStop(" in source and "    NoImprovementStop,\n" in source
    assert "JudgeStop" not in source
    only = render_workflow_source(loop_document(threshold))
    assert "NoImprovementStop" not in only
    assert (
        document.definition.declaration_digest() != loop_document().definition.declaration_digest()
    )
    with pytest.raises(ValidationError, match="judge stop conditions are deferred"):
        JudgeStop()
    with pytest.raises(WorkflowSourceError):
        parse_workflow_source(
            source.replace(
                "    NoImprovementStop,\n", "    NoImprovementStop,\n    JudgeStop,\n", 1
            )
            .replace("NoImprovementStop(\n", "JudgeStop(\n", 1)
            .replace("                    completed_bodies=2,\n", "", 1)
            .replace("kind='no_improvement'", "kind='judge'")
        )
    with pytest.raises(ValidationError, match="more than one stop condition"):
        loop_document(threshold, threshold)
    with pytest.raises(ValidationError, match="below final_iteration"):
        loop_document(NoImprovementStop(completed_bodies=3))
    loop_document(NoImprovementStop(completed_bodies=2))
