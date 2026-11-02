"""Patch validated documents without regenerating untouched Python literals.

Browser proposals compare numbers in their binary64 projection. Values that the
browser cannot distinguish retain their exact source; explicit source proposals
remain the route for changing numeric type, signed zero or literal spelling.
"""

import ast
import math
from collections.abc import Sequence

from .models import AuthoredWorkflowDocument, DeclarationModel
from .source import _fail, _render_value, parse_workflow_source, render_workflow_source
from .source_edits import _apply, _Bytes, _import_edit, _root


def _equal(old: object, new: object, browser_numbers: bool) -> bool:
    if isinstance(old, DeclarationModel) and type(old) is type(new):
        return all(
            _equal(getattr(old, name), getattr(new, name), browser_numbers)
            for name in type(old).model_fields
        )
    if isinstance(old, dict) and isinstance(new, dict):
        return old.keys() == new.keys() and all(
            _equal(value, new[key], browser_numbers) for key, value in old.items()
        )
    if isinstance(old, (tuple, list)) and type(old) is type(new):
        return len(old) == len(new) and all(  # type: ignore[arg-type]
            _equal(a, b, browser_numbers)
            for a, b in zip(old, new, strict=True)  # type: ignore[arg-type]
        )
    if browser_numbers and new is None and type(old) is int:
        try:
            float(old)
        except OverflowError:
            return True  # JSON.stringify(Infinity) is null.
    if type(old) in (int, float) and type(new) in (int, float):
        if browser_numbers:
            try:
                return float(old) == float(new)  # type: ignore[arg-type]
            except OverflowError:
                return old == new
        if type(old) is float and type(new) is float and old == new == 0:
            return math.copysign(1, old) == math.copysign(1, new)
    return type(old) is type(new) and old == new


def restore_browser_values(source: str, value: object) -> object:
    """Recover untouched numbers before typed document admission (including overflow).

    The exact bounded source is the baseline; new/changed values still go through
    normal declaration validation. Never execute the source or infer new values.
    """
    baseline = parse_workflow_source(source).model_dump(mode="json")
    return _restore(baseline, value)


def _restore(old: object, new: object) -> object:
    if _equal(old, new, True):
        return old
    if isinstance(old, dict) and isinstance(new, dict):
        return {
            key: _restore(old[key], value) if key in old else value for key, value in new.items()
        }
    if isinstance(old, list) and isinstance(new, list):
        key = next(
            (
                name
                for name in ("id", "node", "name")
                if old
                and new
                and all(
                    isinstance(item, dict) and isinstance(item.get(name), str)
                    for item in (*old, *new)
                )
            ),
            None,
        )
        indexed = {(item[key] if key else index): item for index, item in enumerate(old)}
        return [
            _restore(indexed[identity], item)
            if (identity := item[key] if key else index) in indexed
            else item
            for index, item in enumerate(new)
        ]
    return _browser_scalar(old, new)


def _browser_scalar(old: object, new: object) -> object:
    """JSON integers cannot express an intentional change of an authored float type."""
    if type(old) is float and type(new) is int:
        try:
            return float(new)
        except OverflowError:
            _fail("validation", "edited value exceeds the authored float range")
    return new


class _Update:
    def __init__(self, source: str, browser_numbers: bool):
        self.text = _Bytes(source)
        self.browser_numbers = browser_numbers

    def original(self, node: ast.AST) -> bytes:
        return self.text.data[self.text.start(node) : self.text.end(node)]

    def render(self, value: object) -> bytes:
        return _render_value(value, 0).encode().replace(b"\n", self.text.newline)

    def replace(self, node: ast.AST, edits: list[tuple[int, int, bytes]]) -> bytes:
        start = self.text.start(node)
        return _apply(
            self.original(node), ((a - start, b - start, v) for a, b, v in edits)
        ).encode()

    def value(self, node: ast.expr, old: object, new: object) -> bytes:
        if _equal(old, new, self.browser_numbers):
            return self.original(node)
        if (
            isinstance(old, DeclarationModel)
            and type(old) is type(new)
            and isinstance(node, ast.Call)
        ):
            return self.model(node, old, new)
        if isinstance(old, dict) and isinstance(new, dict) and isinstance(node, ast.Dict):
            return self.mapping(node, old, new)
        if (
            isinstance(old, (list, tuple))
            and isinstance(new, (list, tuple))
            and isinstance(node, (ast.List, ast.Tuple))
        ):
            return self.sequence(node, old, new)
        return self.render(_browser_scalar(old, new) if self.browser_numbers else new)

    def model(self, node: ast.Call, old: DeclarationModel, new: object) -> bytes:
        keywords = {item.arg: item.value for item in node.keywords}
        edits = []
        added = []
        for name in type(old).model_fields:
            before, after = getattr(old, name), getattr(new, name)
            if _equal(before, after, self.browser_numbers):
                continue
            if name in keywords:
                child = keywords[name]
                edits.append(
                    (self.text.start(child), self.text.end(child), self.value(child, before, after))
                )
            else:
                added.append(name.encode() + b"=" + self.render(after))
        if added:
            # Insert before ')' without disturbing an existing trailing comment.
            last = node.keywords[-1] if node.keywords else None
            if last is not None and self.text.comma_after(self.text.end(last)) is None:
                end = self.text.end(last)
                edits.append((end, end, b","))
            end = self.text.end(node) - 1
            edits.append(
                (end, end, self.text.newline + b", ".join(added) + b"," + self.text.newline)
            )
        return self.replace(node, edits)

    def mapping(self, node: ast.Dict, old: dict[str, object], new: dict[str, object]) -> bytes:
        entries = {
            ast.literal_eval(key): (key, value)
            for key, value in zip(node.keys, node.values, strict=True)
            if key is not None
        }
        if old.keys() == new.keys():
            return self.replace(
                node,
                [
                    (
                        self.text.start(child),
                        self.text.end(child),
                        self.value(child, old[key], new[key]),
                    )
                    for key, (_, child) in entries.items()
                ],
            )
        parts = []
        for key, value in new.items():
            if key in entries:
                key_node, child = entries[key]
                parts.append(self.original(key_node) + b": " + self.value(child, old[key], value))
            else:
                parts.append(self.render(key) + b": " + self.render(value))
        return b"{" + b", ".join(parts) + b"}"

    def sequence(
        self, node: ast.List | ast.Tuple, old: Sequence[object], new: Sequence[object]
    ) -> bytes:
        # Declaration collections have stable identities; deletion must not match
        # the next node/position/argument against the removed element's source.
        key = next(
            (
                name
                for name in ("id", "node", "name")
                if old
                and new
                and all(isinstance(getattr(item, name, None), str) for item in (*old, *new))
            ),
            None,
        )
        indexed = {
            (getattr(item, key) if key else index): (item, child)
            for index, (item, child) in enumerate(zip(old, node.elts, strict=True))
        }
        parts = []
        edits = []
        same_order = len(old) == len(new) and (
            key is None or [getattr(v, key) for v in old] == [getattr(v, key) for v in new]
        )
        for index, item in enumerate(new):
            previous = indexed.get(getattr(item, key) if key else index)
            if previous is None:
                parts.append(self.render(item))
            else:
                before, child = previous
                part = self.value(child, before, item)
                parts.append(part)
                edits.append((self.text.start(child), self.text.end(child), part))
        if same_order:
            return self.replace(node, edits)
        if isinstance(node, ast.Tuple):
            return b"(" + b", ".join(parts) + (b"," if parts else b"") + b")"
        return b"[" + b", ".join(parts) + b"]"


def update_workflow_source(
    source: str, document: AuthoredWorkflowDocument, *, browser_numbers: bool = False
) -> str:
    """Retain exact unedited value spans; validate the resulting declaration.

    Constructor/collection changes may change their surrounding formatting, but
    retained members are patched recursively. Never import or execute source.
    """
    # Preserve the renderer's validation diagnostics for unchecked model_copy
    # proposals (notably loop cross-field errors) before locating source spans.
    render_workflow_source(document)
    old = parse_workflow_source(source)
    module = ast.parse(source)
    root = _root(module)
    update = _Update(source, browser_numbers)
    edits = [(update.text.start(root), update.text.end(root), update.value(root, old, document))]
    calls = {
        item.func.id
        for item in ast.walk(ast.parse(edits[0][2]))
        if isinstance(item, ast.Call) and isinstance(item.func, ast.Name)
    }
    imported = _import_edit(update.text, module, calls)
    if imported is not None:
        edits.append(imported)
    result = _apply(update.text.data, edits)
    parsed = parse_workflow_source(result)
    # Keep canonical add/remove round trips canonical too. Untouched values have
    # already been restored from source, so this cannot introduce JSON losses.
    if source == render_workflow_source(old):
        return render_workflow_source(parsed)
    return result
