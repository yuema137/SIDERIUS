"""Targeted node insertion and removal in restricted declaration source.

Only the affected tuple elements (and missing constructor import names) change;
every other byte, including comments and formatting, is kept. Spans come from
Python's AST over the exact UTF-8 bytes; nothing is imported or evaluated. The
caller re-parses the result with ``parse_workflow_source``, which stays the only
declaration validator, so an edit here can never admit an invalid document.
"""

import ast
from collections.abc import Iterable

from .models import DeclarationModel, NodeInstance, NodePosition
from .source import _render_value, parse_workflow_source


class SourceEditError(ValueError):
    """The exact source has no unambiguous location for the requested edit."""


class _Bytes:
    """UTF-8 byte offsets for AST (one-based line, byte column) positions."""

    def __init__(self, source: str) -> None:
        self.data = source.encode("utf-8")
        self.starts = [0]
        for line in self.data.splitlines(keepends=True):
            self.starts.append(self.starts[-1] + len(line))

    def start(self, node: ast.AST) -> int:
        return self.starts[node.lineno - 1] + node.col_offset  # type: ignore[attr-defined]

    def end(self, node: ast.AST) -> int:
        return self.starts[node.end_lineno - 1] + node.end_col_offset  # type: ignore[attr-defined]

    def line_start(self, offset: int) -> int:
        return self.data.rfind(b"\n", 0, offset) + 1

    def line_end(self, offset: int) -> int:
        """Offset just after the newline ending ``offset``'s line (or EOF)."""
        newline = self.data.find(b"\n", offset)
        return len(self.data) if newline < 0 else newline + 1

    def skip_blank(self, offset: int) -> int:
        while offset < len(self.data) and self.data[offset] in b" \t":
            offset += 1
        return offset

    def indent(self, offset: int) -> bytes:
        """Leading whitespace of the line containing ``offset``."""
        start = self.line_start(offset)
        return self.data[start : self.skip_blank(start)]


def _root(module: ast.Module) -> ast.Call:
    for statement in module.body:
        if isinstance(statement, ast.Assign) and isinstance(statement.value, ast.Call):
            return statement.value
    raise SourceEditError("source has no document constructor")


def _keyword(call: ast.Call, name: str) -> ast.keyword | None:
    return next((item for item in call.keywords if item.arg == name), None)


def _call_keyword(call: ast.Call, name: str) -> ast.Call:
    keyword = _keyword(call, name)
    if keyword is None or not isinstance(keyword.value, ast.Call):
        raise SourceEditError(f"source has no {name} constructor")
    return keyword.value


def _tuple_keyword(call: ast.Call, name: str) -> ast.Tuple | None:
    keyword = _keyword(call, name)
    if keyword is None:
        return None
    if not isinstance(keyword.value, ast.Tuple):
        raise SourceEditError(f"{name} must be a literal tuple for targeted edits")
    return keyword.value


def _constant(call: ast.expr, name: str) -> object:
    if not isinstance(call, ast.Call):
        return None
    keyword = _keyword(call, name)
    return keyword.value.value if keyword and isinstance(keyword.value, ast.Constant) else None


def _render(value: DeclarationModel, indent: bytes) -> bytes:
    lines = _render_value(value, 0).encode("utf-8").split(b"\n")
    return b"\n".join([lines[0], *(indent + line for line in lines[1:])])


def _append(text: _Bytes, container: ast.Tuple, value: DeclarationModel) -> tuple[int, int, bytes]:
    """Insert one element after the last element of a literal tuple."""
    if not container.elts:
        # ``()`` becomes a one-element block indented under the owning keyword line.
        outer = text.indent(text.start(container))
        inner = outer + b"    "
        body = b"(\n" + inner + _render(value, inner) + b",\n" + outer + b")"
        return text.start(container), text.end(container), body
    last = container.elts[-1]
    begin, end = text.start(last), text.end(last)
    alone = text.skip_blank(text.line_start(begin)) == begin
    indent = text.indent(begin) if alone else b" " * last.col_offset
    after = text.skip_blank(end)
    if after < len(text.data) and text.data[after : after + 1] == b",":
        return after + 1, after + 1, b"\n" + indent + _render(value, indent) + b","
    return end, end, b",\n" + indent + _render(value, indent)


def _element_span(text: _Bytes, container: ast.Tuple, index: int) -> tuple[int, int]:
    """Bytes owning one tuple element: whole lines when it stands alone on them."""
    element = container.elts[index]
    begin, end = text.start(element), text.end(element)
    after = text.skip_blank(end)
    comma = after < len(text.data) and text.data[after : after + 1] == b","
    stop = after + 1 if comma else end
    rest = text.skip_blank(stop)
    line_tail = rest >= len(text.data) or text.data[rest : rest + 1] in (b"\n", b"\r", b"#")
    if text.skip_blank(text.line_start(begin)) == begin and line_tail:
        return text.line_start(begin), text.line_end(stop)
    if comma:
        return begin, text.skip_blank(stop)
    if index == 0:
        return begin, end
    previous = container.elts[index - 1]
    separator = text.data.find(b",", text.end(previous), begin)
    return (separator + 1 if separator >= 0 else text.end(previous)), end


def _apply(data: bytes, edits: Iterable[tuple[int, int, bytes]]) -> str:
    ordered = sorted(edits, key=lambda item: (item[0], item[1]))
    merged: list[tuple[int, int, bytes]] = []
    for begin, end, replacement in ordered:
        if merged and begin < merged[-1][1]:
            previous = merged[-1]
            if replacement or previous[2]:
                raise SourceEditError("overlapping source edits")
            merged[-1] = (previous[0], max(previous[1], end), b"")
        else:
            merged.append((begin, end, replacement))
    for begin, end, replacement in reversed(merged):
        data = data[:begin] + replacement + data[end:]
    return data.decode("utf-8")


def _import_edit(
    text: _Bytes, module: ast.Module, names: set[str]
) -> tuple[int, int, bytes] | None:
    imported = next(item for item in module.body if isinstance(item, ast.ImportFrom))
    missing = [name for name in sorted(names) if name not in {a.name for a in imported.names}]
    if not missing:
        return None
    last = imported.names[-1]
    end = text.end(last)
    after = text.skip_blank(end)
    if after < len(text.data) and text.data[after : after + 1] == b",":
        # A trailing-comma block (canonical style): one name per line.
        indent = text.indent(text.start(last))
        return after + 1, after + 1, b"".join(b"\n" + indent + n.encode() + b"," for n in missing)
    return end, end, b"".join(b", " + name.encode() for name in missing)


def _constructors(value: DeclarationModel) -> set[str]:
    names = {type(value).__name__}
    for field in type(value).model_fields:
        item = getattr(value, field)
        for child in item if isinstance(item, tuple) else (item,):
            if isinstance(child, DeclarationModel):
                names |= _constructors(child)
    return names


def insert_node(source: str, node: NodeInstance, position: NodePosition) -> str:
    """Append one node and its layout position; the result is not yet validated."""
    module = ast.parse(source)
    text = _Bytes(source)
    root = _root(module)
    definition = _call_keyword(root, "definition")
    nodes = _tuple_keyword(definition, "nodes")
    if nodes is None:
        raise SourceEditError("definition has no nodes tuple")
    edits = [_append(text, nodes, node)]
    positions = _tuple_keyword(root, "positions")
    if positions is not None:
        edits.append(_append(text, positions, position))
    else:
        last = root.keywords[-1]
        indent = text.indent(text.start(last))
        block = b"positions=(\n" + indent + b"    " + _render(position, indent + b"    ")
        block += b",\n" + indent + b")"
        after = text.skip_blank(text.end(last.value))
        if text.data[after : after + 1] == b",":
            edits.append((after + 1, after + 1, b"\n" + indent + block + b","))
        else:
            edits.append((text.end(last.value), text.end(last.value), b", " + block))
    if (imports := _import_edit(text, module, _constructors(node) | {"NodePosition"})) is not None:
        edits.append(imports)
    return _apply(text.data, edits)


def remove_nodes(source: str, nodes: tuple[str, ...]) -> str:
    """Remove nodes (with their own request bindings) and their layout positions.

    The caller refuses removals that other nodes still read. Constructor imports
    are left as written; an unused import is still valid declaration source.
    """
    parse_workflow_source(source)
    module = ast.parse(source)
    text = _Bytes(source)
    root = _root(module)
    node_tuple = _tuple_keyword(_call_keyword(root, "definition"), "nodes")
    assert node_tuple is not None
    removed = set(nodes)
    edits: list[tuple[int, int, bytes]] = []
    found: set[object] = set()
    for index, element in enumerate(node_tuple.elts):
        if (identity := _constant(element, "id")) in removed:
            found.add(identity)
            edits.append((*_element_span(text, node_tuple, index), b""))
    if found != removed:
        raise SourceEditError("node ids must be written as plain string literals")
    positions = _tuple_keyword(root, "positions")
    for index, element in enumerate(positions.elts if positions else ()):
        if _constant(element, "node") in removed:
            assert positions is not None
            edits.append((*_element_span(text, positions, index), b""))
    return _apply(text.data, edits)
