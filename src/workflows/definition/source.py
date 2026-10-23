"""Inert conversion between restricted declaration source and existing models.

Only Python's AST is read. Selected modules and referenced resources are never
imported, evaluated or opened. Admission limits are local to this converter.
"""

import ast
import math
from typing import Literal, NoReturn

from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic_core import PydanticSerializationError

from .models import (
    ArgumentBinding,
    AuthoredWorkflowDocument,
    CandidatePreparationOptions,
    DeclarationModel,
    ExternalBinding,
    ExternalRequest,
    ExternalSource,
    ManagedCandidateBinding,
    NodeInstance,
    NodePosition,
    ProtocolRequest,
    ResultSource,
    ReusableTaskReferences,
    ReusableWorkflowDefinition,
    ReusableWorkflowDocument,
    TaskReferences,
    WorkflowDefinition,
    WorkflowDocument,
    revalidate_document,
)

MAX_INPUT_BYTES = 1024 * 1024
MAX_AST_NODES = 100_000
MAX_AST_DEPTH = 64

# This is deliberately independent of the package's public export list.
_CONSTRUCTORS: dict[str, type[DeclarationModel]] = {
    model.__name__: model
    for model in (
        CandidatePreparationOptions,
        ManagedCandidateBinding,
        ReusableTaskReferences,
        ReusableWorkflowDefinition,
        ReusableWorkflowDocument,
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
}
_FIELD_NAMES = frozenset(name for model in _CONSTRUCTORS.values() for name in model.model_fields)


class SourceDiagnostic(BaseModel):
    """Source spans use one-based lines and zero-based UTF-8 byte columns."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    code: Literal["syntax", "unsupported", "limit", "validation"]
    message: str
    line: int | None = None
    column: int | None = None
    end_line: int | None = None
    end_column: int | None = None
    field_path: tuple[str | int, ...] | None = None


class WorkflowSourceError(ValueError):
    """A failed conversion has diagnostics and never a partial document."""

    def __init__(self, diagnostics: tuple[SourceDiagnostic, ...]) -> None:
        if not diagnostics:
            raise ValueError("At least one diagnostic is required")
        self.diagnostics = diagnostics
        super().__init__("; ".join(item.message for item in diagnostics))


def _fail(
    code: Literal["syntax", "unsupported", "limit", "validation"],
    message: str,
    node: ast.AST | None = None,
    field_path: tuple[str | int, ...] | None = None,
) -> NoReturn:
    raise WorkflowSourceError(
        (
            SourceDiagnostic(
                code=code,
                message=message,
                line=getattr(node, "lineno", None),
                column=getattr(node, "col_offset", None),
                end_line=getattr(node, "end_lineno", None),
                end_column=getattr(node, "end_col_offset", None),
                field_path=field_path,
            ),
        )
    )


def _validation_error(error: ValidationError, node: ast.AST | None = None) -> NoReturn:
    # Native custom-validator messages can interpolate source values. Never
    # forward msg/input/ctx, including unknown JSON keys in error locations.
    first = error.errors(include_input=False, include_context=False, include_url=False)[0]
    path = tuple(
        part if isinstance(part, int) or part in _FIELD_NAMES else "<value>"
        for part in first["loc"]
    )
    _fail("validation", "Declaration validation failed", node, path or None)


def _check_resources(module: ast.Module) -> None:
    pending: list[tuple[ast.AST, int]] = [(module, 1)]
    count = 0
    while pending:
        node, depth = pending.pop()
        count += 1
        if count > MAX_AST_NODES:
            _fail("limit", "AST node limit exceeded")
        if depth > MAX_AST_DEPTH:
            _fail("limit", "AST depth limit exceeded", node)
        pending.extend((child, depth + 1) for child in ast.iter_child_nodes(node))


def _syntax_diagnostic(error: SyntaxError, source: str) -> NoReturn:
    # Python recognizes CR and CRLF as newlines, but U+2028/U+0085 may
    # occur inside string literals and must not shift diagnostic lines.
    lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    def byte_column(line: int | None, offset: int | None) -> int | None:
        if line is None or offset is None or not 1 <= line <= len(lines):
            return None
        return len(lines[line - 1][: max(offset - 1, 0)].encode("utf-8"))

    raise WorkflowSourceError(
        (
            SourceDiagnostic(
                code="syntax",
                message="Invalid Python declaration syntax",
                line=error.lineno,
                column=byte_column(error.lineno, error.offset),
                end_line=error.end_lineno,
                end_column=byte_column(error.end_lineno, error.end_offset),
            ),
        )
    )


def _module_declaration(module: ast.Module) -> tuple[set[str], ast.Call]:
    statements = module.body
    if statements and isinstance(statements[0], ast.Expr):
        value = statements[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            statements = statements[1:]
    if len(statements) < 2:
        _fail("unsupported", "Expected one constructor import and one document assignment", module)
    imported, assignment = statements[:2]
    if not isinstance(imported, ast.ImportFrom):
        _fail("unsupported", "Expected an absolute constructor import", imported)
    if imported.module != "workflows.definition" or imported.level != 0:
        _fail(
            "unsupported", "Only workflows.definition constructor imports are supported", imported
        )
    names: set[str] = set()
    for alias in imported.names:
        if alias.asname or alias.name not in _CONSTRUCTORS or alias.name in names:
            _fail("unsupported", "Expected unique allowlisted constructors without aliases", alias)
        names.add(alias.name)
    if (
        not isinstance(assignment, ast.Assign)
        or len(assignment.targets) != 1
        or not isinstance(assignment.targets[0], ast.Name)
        or assignment.targets[0].id != "document"
    ):
        _fail("unsupported", "Expected a single document assignment", assignment)
    if len(statements) > 2:
        _fail("unsupported", "Unexpected statement after document assignment", statements[2])
    root = assignment.value
    if (
        not isinstance(root, ast.Call)
        or not isinstance(root.func, ast.Name)
        or root.func.id not in {"WorkflowDocument", "ReusableWorkflowDocument"}
    ):
        _fail("unsupported", "The root must be WorkflowDocument or ReusableWorkflowDocument", root)
    return names, root


def _check_value(node: ast.expr, imported: set[str]) -> None:
    """Check the complete constructor grammar before invoking any models."""
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in imported:
            _fail("unsupported", "Calls require an imported bare constructor", node)
        if node.args:
            _fail("unsupported", "Constructor arguments must be keywords", node)
        fields = _CONSTRUCTORS[node.func.id].model_fields
        seen: set[str] = set()
        for keyword in node.keywords:
            if keyword.arg is None or keyword.arg in seen or keyword.arg not in fields:
                _fail("unsupported", "Unknown, duplicate or expanded constructor keyword", keyword)
            seen.add(keyword.arg)
            if keyword.arg == "training_settings":
                _check_json_value(keyword.value)
            else:
                _check_value(keyword.value, imported)
        return
    if isinstance(node, ast.Tuple):
        for element in node.elts:
            _check_value(element, imported)
        return
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, (ast.UAdd, ast.USub))
        and isinstance(node.operand, ast.Constant)
        and type(node.operand.value) in (int, float)
    ):
        _check_value(node.operand, imported)
        return
    if isinstance(node, ast.Constant):
        value = node.value
        if value is None or type(value) in (str, bool, int):
            return
        if type(value) is float:
            if not math.isfinite(value):
                _fail("validation", "Numeric literals must be finite", node)
            return
    _fail("unsupported", "Unsupported declaration expression", node)


def _check_json_value(node: ast.expr) -> None:
    """Only inert JSON-shaped literals, with duplicate keys refused before construction."""
    if isinstance(node, ast.Dict):
        keys: set[str] = set()
        for key, value in zip(node.keys, node.values, strict=True):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                _fail("unsupported", "JSON mappings require literal string keys", node)
            if key.value in keys:
                _fail("unsupported", "Duplicate JSON mapping key", key)
            keys.add(key.value)
            _check_json_value(value)
        return
    if isinstance(node, ast.List):
        for value in node.elts:
            _check_json_value(value)
        return
    if not isinstance(node, (ast.Constant, ast.UnaryOp)):
        _fail("unsupported", "Training settings require inert JSON literals", node)
    _check_value(node, set())


def _construct(node: ast.expr) -> object:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        values = {keyword.arg: _construct(keyword.value) for keyword in node.keywords}
        try:
            return _CONSTRUCTORS[node.func.id](**values)  # type: ignore[arg-type]
        except ValidationError as error:
            _validation_error(error, node)
    if isinstance(node, ast.Dict):
        return {
            _construct(key): _construct(value)
            for key, value in zip(node.keys, node.values, strict=True)
            if key is not None
        }
    if isinstance(node, ast.List):
        return [_construct(value) for value in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_construct(element) for element in node.elts)
    if isinstance(node, ast.UnaryOp) and isinstance(node.operand, ast.Constant):
        value = node.operand.value
        assert isinstance(value, (int, float)) and not isinstance(value, bool)
        return -value if isinstance(node.op, ast.USub) else +value
    if isinstance(node, ast.Constant):
        return node.value
    raise AssertionError("Constructor traversal requires prevalidated AST")


def parse_workflow_source(source: str) -> AuthoredWorkflowDocument:
    """Parse the restricted dedicated module without executing selected source."""
    try:
        size = len(source.encode("utf-8"))
    except UnicodeEncodeError:
        _fail("syntax", "Source must be valid UTF-8 text")
    if size > MAX_INPUT_BYTES:
        _fail("limit", "Input exceeds the 1 MiB byte limit")
    try:
        module = ast.parse(source)
    except SyntaxError as error:
        _syntax_diagnostic(error, source)
    except RecursionError:
        _fail("limit", "Python parser recursion limit exceeded")
    except ValueError:
        # Includes numeric conversion admission errors; never echo parser text.
        _fail("syntax", "Invalid Python declaration literal")
    _check_resources(module)
    imported, root = _module_declaration(module)
    _check_value(root, imported)
    document = _construct(root)
    assert isinstance(document, (WorkflowDocument, ReusableWorkflowDocument))
    return document


def _render_value(value: object, depth: int) -> str:
    indentation = "    " * depth
    child_indent = "    " * (depth + 1)
    if isinstance(value, DeclarationModel):
        fields = [
            f"{child_indent}{name}={_render_value(getattr(value, name), depth + 1)},"
            for name in type(value).model_fields
            if not (name == "training_settings" and getattr(value, name) is None)
        ]
        return f"{type(value).__name__}(\n" + "\n".join(fields) + f"\n{indentation})"
    if isinstance(value, tuple):
        if not value:
            return "()"
        elements = [f"{child_indent}{_render_value(item, depth + 1)}," for item in value]
        return "(\n" + "\n".join(elements) + f"\n{indentation})"
    if isinstance(value, dict):
        if not value:
            return "{}"
        elements = [
            f"{child_indent}{key!r}: {_render_value(item, depth + 1)},"
            for key, item in value.items()
        ]
        return "{\n" + "\n".join(elements) + f"\n{indentation}}}"
    if isinstance(value, list):
        return "[" + ", ".join(_render_value(item, depth + 1) for item in value) + "]"
    if value is None or type(value) in (str, int, bool, float):
        return repr(value)
    raise AssertionError("Renderer requires a revalidated declaration")


def render_workflow_source(document: AuthoredWorkflowDocument) -> str:
    """Return canonical complete source, revalidating unchecked model instances."""
    try:
        validated = revalidate_document(document)
    except ValidationError as error:
        _validation_error(error)
    except PydanticSerializationError:
        _fail("validation", "Declaration cannot be serialized for revalidation")
    constructors = _CONSTRUCTORS
    if isinstance(validated, WorkflowDocument):
        # Keep the v1 canonical source byte-identical as its allowlist grows.
        constructors = {
            name: model
            for name, model in constructors.items()
            if name
            not in {
                "CandidatePreparationOptions",
                "ManagedCandidateBinding",
                "ReusableTaskReferences",
                "ReusableWorkflowDefinition",
                "ReusableWorkflowDocument",
            }
        }
    imports = "\n".join(f"    {name}," for name in constructors)
    source = (
        "# Generated workflow declaration; comments and formatting are not preserved.\n"
        f"from workflows.definition import (\n{imports}\n)\n\n"
        f"document = {_render_value(validated, 0)}\n"
    )
    parse_workflow_source(source)
    return source
