"""Forbidden-pattern static check for agent-generated nn.Module plugins.

Single rule: an `nn.Module.forward` may not contain a `for` or `while` loop
that iterates over the time/sequence dimension. Such loops cause RAM OOMs
and CPU hangs at long T (V11 kill mode at T=200,000 was a Python time-loop
inside `forward`).

Detection is AST-based and intentionally conservative:

    - Only loops *inside `forward(...)` of an `nn.Module` subclass* are
      considered. Loops in `__init__` (e.g. `nn.ModuleList` construction)
      or in helper methods are out of scope.
    - For-loops are flagged when the iterator is `range(EXPR)` where EXPR
      references one of the canonical time names (`seq_len`, `T`,
      `time_steps`) or a tensor-shape access on the time axis
      (`*.shape[1]`, `*.shape[-1]`, `*.size(1)`, `*.size(-1)`), including
      reversed-stride forms `range(EXPR - 1, -1, -1)`.
    - While-loops in `forward` are flagged unconditionally — legitimate
      cases are vanishingly rare and any false positive is worth less than
      the cost of letting a Python time-loop reach the VRAM probe.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

_TIME_NAMES: frozenset[str] = frozenset({"seq_len", "T", "time_steps"})
_TIME_AXIS_INDICES: frozenset[int] = frozenset({1, -1})

_ERROR_MESSAGE = (
    "Naive Python loops over the time dimension (T) are forbidden at "
    r"$T \ge 80,000$. Use vectorized operations (FFT, Linear Attention, "
    "or Associative Scans via torch.cumsum) to ensure physical viability."
)


@dataclass
class ForbiddenLoopHit:
    method: str
    lineno: int
    kind: str
    snippet: str


def _is_time_axis_index(slice_node: ast.AST) -> bool:
    """Return True if the subscript index is 1 or -1."""
    if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, int):
        return slice_node.value in _TIME_AXIS_INDICES
    return (
        isinstance(slice_node, ast.UnaryOp)
        and isinstance(slice_node.op, ast.USub)
        and isinstance(slice_node.operand, ast.Constant)
        and isinstance(slice_node.operand.value, int)
        and -slice_node.operand.value in _TIME_AXIS_INDICES
    )


def _references_time_dim(expr: ast.AST) -> bool:
    """Return True if `expr` is a time-dim sentinel: a canonical name,
    a `*.shape[1|-1]` subscript, or a `*.size(1|-1)` call."""
    if isinstance(expr, ast.Name) and expr.id in _TIME_NAMES:
        return True
    if isinstance(expr, ast.Attribute) and expr.attr in _TIME_NAMES:
        return True
    if (
        isinstance(expr, ast.Subscript)
        and isinstance(expr.value, ast.Attribute)
        and expr.value.attr == "shape"
    ):
        return _is_time_axis_index(expr.slice)
    if (
        isinstance(expr, ast.Call)
        and isinstance(expr.func, ast.Attribute)
        and expr.func.attr == "size"
        and len(expr.args) == 1
    ):
        return _is_time_axis_index(expr.args[0])
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, (ast.Sub, ast.Add)):
        return _references_time_dim(expr.left) or _references_time_dim(expr.right)
    return False


def _is_range_over_time(call: ast.AST) -> bool:
    """Return True if `call` is `range(EXPR)` whose first arg references the
    time dimension. Covers `range(T)`, `range(x.shape[1])`,
    `range(T-1, -1, -1)`, etc."""
    if not (
        isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "range"
    ):
        return False
    return any(_references_time_dim(a) for a in call.args)


def _iter_forward_methods(tree: ast.AST):
    """Yield every `forward` method body in any `class` (we don't restrict
    to nn.Module subclasses statically; the validator's instantiation
    check already enforces nn.Module inheritance, and a `forward` method
    in a non-Module class is itself unusual enough to flag)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if (
                    isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and item.name == "forward"
                ):
                    yield item


def scan(source: str) -> list[ForbiddenLoopHit]:
    """Walk `source`, return one ForbiddenLoopHit per offending loop."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [
            ForbiddenLoopHit(
                method="<module>",
                lineno=e.lineno or 0,
                kind="syntax",
                snippet=f"SyntaxError: {e.msg}",
            )
        ]

    hits: list[ForbiddenLoopHit] = []
    for forward in _iter_forward_methods(tree):
        for node in ast.walk(forward):
            if isinstance(node, ast.For) and _is_range_over_time(node.iter):
                hits.append(
                    ForbiddenLoopHit(
                        method=forward.name,
                        lineno=node.lineno,
                        kind="for",
                        snippet=ast.unparse(node.iter),
                    )
                )
            elif isinstance(node, ast.While):
                hits.append(
                    ForbiddenLoopHit(
                        method=forward.name,
                        lineno=node.lineno,
                        kind="while",
                        snippet=ast.unparse(node.test),
                    )
                )
    return hits


def check_source(source: str) -> tuple[bool, str | None]:
    """Public entry. Returns (passed, error_message). `error_message` is
    None when passed=True; otherwise it lists every offending loop."""
    hits = scan(source)
    if not hits:
        return True, None
    lines = [_ERROR_MESSAGE, "Offending loops:"]
    for h in hits:
        lines.append(f"  - {h.kind} @ {h.method}:{h.lineno} → {h.snippet}")
    return False, "\n".join(lines)


def check_file(path: str) -> tuple[bool, str | None]:
    """Convenience wrapper that reads `path` and delegates to check_source."""
    with open(path, encoding="utf-8") as f:
        return check_source(f.read())
