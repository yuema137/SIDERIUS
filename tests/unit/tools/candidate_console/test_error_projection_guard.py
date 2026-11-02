"""Syntactic tripwire for exception text entering console views (#1249/#1265)."""

import ast
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4] / "src/tools/candidate_console"
BASELINE = Path(__file__).with_name("error_projection_followups.json")


def _logging(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in {"logger", "logging", "log"}
        and node.func.attr in {"debug", "info", "warning", "error", "exception", "critical"}
    )


def _mentions_exception(node: ast.AST, caught: set[str]) -> bool:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id in {
            "console_error_message",
            "advice_error_message",
            "summary_error_message",
            "error_category",
        }:
            return False
    if isinstance(node, ast.Name):
        return node.id in caught
    return any(_mentions_exception(child, caught) for child in ast.iter_child_nodes(node))


def _message_attribute(node: ast.AST, caught: set[str]) -> bool:
    if not isinstance(node, ast.Attribute):
        return False
    if node.attr == "args":
        return _mentions_exception(node.value, caught)
    if node.attr != "message":
        return False
    return _mentions_exception(node.value, caught | {"failure"}) or any(
        isinstance(item, ast.Attribute) and item.attr == "failure" for item in ast.walk(node.value)
    )


def _formatting_call(node: ast.Call, caught: set[str], formatters: set[str]) -> bool:
    name = node.func.id if isinstance(node.func, ast.Name) else None
    method = node.func.attr if isinstance(node.func, ast.Attribute) else None
    return (name in formatters or method == "format") and any(
        _mentions_exception(arg, caught)
        for arg in (*node.args, *(kw.value for kw in node.keywords))
    )


def _raw_expression(node: ast.AST, caught: set[str], formatters: set[str]) -> bool:
    """Recognize direct formatting, exception args and nested failure messages."""
    if isinstance(node, ast.Call):
        return _formatting_call(node, caught, formatters)
    if isinstance(node, ast.FormattedValue):
        return _mentions_exception(node.value, caught)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        return _mentions_exception(node.right, caught)
    return _message_attribute(node, caught)


def _scope_nodes(scope: ast.AST) -> Iterator[ast.AST]:
    """Do not let an exception binding contaminate a sibling or nested function."""
    yield scope
    for child in ast.iter_child_nodes(scope):
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            yield from _scope_nodes(child)


def _alias_value(node: ast.AST, caught: set[str], formatters: set[str]) -> bool:
    if isinstance(node, ast.IfExp):
        return _alias_value(node.body, caught, formatters) or _alias_value(
            node.orelse, caught, formatters
        )
    if isinstance(node, ast.Call):
        return _raw_expression(node, caught, formatters)
    if isinstance(node, ast.Name):
        return node.id in caught
    if isinstance(node, ast.Attribute) and node.attr == "failure":
        return True
    return _message_attribute(node, caught) or any(
        _alias_value(child, caught, formatters) for child in ast.iter_child_nodes(node)
    )


def _exception_parameters(scope: ast.AST) -> set[str]:
    if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return set()
    return {
        argument.arg
        for argument in (*scope.args.posonlyargs, *scope.args.args, *scope.args.kwonlyargs)
        if argument.annotation is not None
        and any(
            isinstance(part, ast.Name)
            and (
                part.id.endswith(("Error", "Exception", "Refused", "Refusal", "Failure"))
                or part.id in {"MissingConfigFile", "SettingsInvalid", "CredentialFileNotAdded"}
            )
            for part in ast.walk(argument.annotation)
        )
    }


def _bindings(target: ast.AST, value: ast.AST) -> Iterator[tuple[ast.AST, ast.AST]]:
    if (
        isinstance(target, (ast.Tuple, ast.List))
        and isinstance(value, (ast.Tuple, ast.List))
        and len(target.elts) == len(value.elts)
    ):
        for child, item in zip(target.elts, value.elts, strict=True):
            yield from _bindings(child, item)
    else:
        yield target, value


def _stored_names(target: ast.AST) -> set[str]:
    return {
        part.id
        for part in ast.walk(target)
        if isinstance(part, ast.Name) and isinstance(part.ctx, ast.Store)
    }


def _propagate_assignment(
    node: ast.Assign | ast.AnnAssign, caught: set[str], formatters: set[str]
) -> None:
    if node.value is None:
        return
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    for target, value in (pair for assigned in targets for pair in _bindings(assigned, node.value)):
        names = _stored_names(target)
        if _alias_value(value, caught, formatters):
            caught.update(names)
        if isinstance(value, ast.Name) and value.id in formatters:
            formatters.update(names)


def _scope_aliases(nodes: list[ast.AST]) -> tuple[set[str], set[str]]:
    """Conservative local fixed point; unknown helper returns are outside this guard."""
    caught = {node.name for node in nodes if isinstance(node, ast.ExceptHandler) and node.name}
    caught.update(_exception_parameters(nodes[0]))
    formatters = {"str", "repr", "format"}
    assignments = [node for node in nodes if isinstance(node, (ast.Assign, ast.AnnAssign))]
    changed = True
    while changed:
        before = (len(caught), len(formatters))
        for node in assignments:
            _propagate_assignment(node, caught, formatters)
        changed = before != (len(caught), len(formatters))
    return caught, formatters


def _serialization_call(node: ast.Call) -> bool:
    if isinstance(node.func, ast.Attribute):
        return node.func.attr in {"dumps", "dump"}
    return isinstance(node.func, ast.Name) and node.func.id in {"JSONResponse", "dict"}


def _message_keywords(node: ast.Call, caught: set[str], formatters: set[str]) -> bool:
    return any(
        kw.arg in {"message", "detail", "error", "content"}
        and _alias_value(kw.value, caught, formatters)
        for kw in node.keywords
    )


def _serialized_alias(node: ast.AST, caught: set[str], formatters: set[str]) -> bool:
    if isinstance(node, ast.Return) and node.value is not None:
        return _alias_value(node.value, caught, formatters)
    if not isinstance(node, ast.Call):
        return False
    if isinstance(node.func, ast.Attribute) and node.func.attr in {
        "model_dump",
        "model_dump_json",
        "json",
        "dict",
    }:
        return _alias_value(node.func.value, caught, formatters)
    if _message_keywords(node, caught, formatters):
        return True
    if _serialization_call(node):
        return any(
            _alias_value(arg, caught, formatters)
            for arg in (*node.args, *(kw.value for kw in node.keywords))
        )
    return False


def _finding_statement(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> ast.AST | None:
    ancestor = parents.get(node)
    while ancestor is not None:
        if _logging(ancestor):
            return None
        ancestor = parents.get(ancestor)
    while not isinstance(node, ast.stmt) and node in parents:
        node = parents[node]
    return node


def _scope_findings(scope: ast.AST) -> Iterator[ast.AST]:
    nodes = list(_scope_nodes(scope))
    caught, formatters = _scope_aliases(nodes)
    for node in nodes:
        if _raw_expression(node, caught, formatters) or _serialized_alias(node, caught, formatters):
            yield node


def _forwarding(tree: ast.AST) -> list[str]:
    """Bounded lexical aliases supplement the direct-expression review tripwire.

    Unknown helper returns, dynamic attributes and unrelated whole models require
    source review and behavioral boundary witnesses; this is not a taint proof.
    """
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    scopes = [
        tree,
        *(
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda))
        ),
    ]
    statements = {
        statement
        for scope in scopes
        for node in _scope_findings(scope)
        if (statement := _finding_statement(node, parents)) is not None
    }
    return sorted(ast.unparse(statement) for statement in statements)


def test_console_exception_forwarding_has_no_unreviewed_surfaces():
    """Fail on restored task/GPU/setup leaks or any newly introduced direct projection."""
    baseline = json.loads(BASELINE.read_text())
    observed = {
        str(path.relative_to(ROOT)): sorted(_forwarding(ast.parse(path.read_text())))
        for path in ROOT.rglob("*.py")
    }
    observed = {name: expressions for name, expressions in observed.items() if expressions}
    assert observed == baseline["expressions"], (
        "Review the error projection; use the shared category owner and private logging. "
        "Remove repaired legacy exceptions; do not expand the baseline to hide new leaks."
    )


@pytest.mark.parametrize(
    "expression",
    [
        "str(cause)",
        "repr(cause)",
        "format(cause)",
        "f'{cause}'",
        "f'{cause!r}'",
        "'{}'.format(cause)",
        "'{err}'.format(err=cause)",
        "'%s' % cause",
        "'%s' % (cause,)",
        "cause.message",
        "cause.args",
        "str(cause.args[0])",
    ],
)
def test_guard_detects_exception_forwarding(expression):
    """The guard must catch arbitrary exception variable names and all direct spellings."""
    tree = ast.parse(
        f"try:\n    work()\nexcept Exception as cause:\n    return View(message={expression})"
    )
    assert _forwarding(tree)


def test_guard_detects_serialized_failure_and_allows_logging():
    assert _forwarding(ast.parse("return View(message=failure.message)"))
    assert not _forwarding(ast.parse("logger.error('cause: %s', failure.message)"))


@pytest.mark.parametrize("expression", ["x.failure.message", "x.result.failure.message"])
def test_guard_detects_chained_messages(expression):
    assert _forwarding(ast.parse(f"return View(message={expression})"))


def test_guard_counts_duplicate_statements_once_per_occurrence():
    tree = ast.parse(
        "try:\n    work()\nexcept Exception as cause:\n    view(str(cause))\n    view(str(cause))"
    )
    assert _forwarding(tree) == ["view(str(cause))", "view(str(cause))"]
    # Multiple raw subexpressions in one statement must not inflate its count.
    assert len(_forwarding(ast.parse("return str(x.failure.message)"))) == 1


@pytest.mark.parametrize(
    "body",
    [
        "alias = cause\nreturn str(alias)",
        "alias = cause\nnext_alias = alias\nreturn View(message=next_alias)",
        "alias, safe = cause, 'fixed'\nreturn repr(alias)",
        "box = {'cause': cause}\nreturn JSONResponse(content=box)",
        "alias = cause.message\nreturn alias",
        "alias = cause.args\nreturn json.dumps(alias)",
        "show = str\nagain = show\nreturn again(cause)",
        "alias = cause\nreturn alias.model_dump()",
        "alias = cause\nreturn alias.model_dump_json()",
    ],
)
def test_guard_detects_local_aliases_and_whole_exception_serialization(body):
    tree = ast.parse(
        "try:\n    work()\nexcept Exception as cause:\n"
        + "\n".join("    " + line for line in body.splitlines())
    )
    assert _forwarding(tree)


@pytest.mark.parametrize(
    "body",
    [
        "failure = result.failure\nreturn failure.model_dump()",
        "failure = result.failure\nbox = {'failure': failure}\nreturn JSONResponse(content=box)",
        "alias = result.failure.message\nreturn View(message=alias)",
    ],
)
def test_guard_detects_whole_failure_carrier_and_message_alias(body):
    assert _forwarding(ast.parse(body))


@pytest.mark.parametrize(
    "body",
    [
        "alias = cause\nlogger.error('private: %s', alias)",
        "alias = cause\nreturn console_error_message(alias)",
        "alias, safe = cause, 'fixed'\nreturn safe",
        "message = 'invalid' if cause is not None else 'unexpected'\nreturn message",
        "show = str\nreturn show(42)",
    ],
)
def test_guard_keeps_logging_fixed_guidance_and_safe_owners(body):
    tree = ast.parse(
        "try:\n    work()\nexcept Exception as cause:\n"
        + "\n".join("    " + line for line in body.splitlines())
    )
    assert not _forwarding(tree)


def test_aliases_do_not_escape_their_lexical_function():
    tree = ast.parse(
        "def private():\n    try:\n        work()\n    except Exception as cause:\n        alias = cause\n        logger.error('%s', alias)\ndef public():\n    alias = 'fixed'\n    return alias"
    )
    assert not _forwarding(tree)
