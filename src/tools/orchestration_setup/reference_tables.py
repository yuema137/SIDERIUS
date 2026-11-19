"""Regenerate the orchestrator-toolkit reference tables from the installed source.

The toolkit payload documents each node's Pydantic input/output fields, its
standalone CLI options and its Python constructor. Those tables used to be
synced by hand and drifted (#1535). Each generated region in a payload file is
delimited by markers::

    <!-- generated: schema agent.schemas.validator.ValidatorInput -->
    ...
    <!-- end generated -->

with kinds ``schema`` (a Pydantic model's ``model_fields``), ``cli`` (the
argparse parser built by a node module's ``main()``) and ``constructor`` (the
``__init__`` signature of an agent class, read from its source). Everything
outside the markers is hand-written prose and is never touched.

    python -m tools.orchestration_setup.reference_tables --check   # exit 1 on drift
    python -m tools.orchestration_setup.reference_tables --write   # rewrite regions

CLI parsers are captured by calling the module's ``main()`` with
``ArgumentParser.parse_args`` replaced by a function that raises the parser
back to us, so no node module needs a new public builder. Each node's
``main()`` builds its parser before any other effect; a ``main()`` that
returns without parsing is refused.
"""

from __future__ import annotations

import argparse
import ast
import importlib
import inspect
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from unittest import mock

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from core.layout import checkout_root, require_checkout

PAYLOAD_REFERENCES = Path(
    "docs/agent-reference/orchestrator-toolkit/payload/.agents/skills/siderius-toolkit/references"
)
_ADDRESS = re.compile(r" at 0x[0-9a-f]+")
_REGION = re.compile(
    r"(?P<open><!-- generated: (?P<kind>schema|cli|constructor) (?P<target>[\w.]+) -->\n)"
    r"(?P<body>.*?)"
    r"(?P<close><!-- end generated -->)",
    re.DOTALL,
)


def _cell(text: str) -> str:
    """One Markdown table cell: one line, no pipes or backticks breaking the row.

    Object reprs inside annotations (``<function f at 0x7f...>``) lose their
    memory address so the output does not change from one process to the next.
    """
    text = _ADDRESS.sub("", text)
    return " ".join(text.split()).replace("|", "\\|").replace("`", "'")


def _type_name(annotation: Any) -> str:
    if isinstance(annotation, type):
        if annotation.__module__ == "builtins":
            return annotation.__qualname__
        return f"{annotation.__module__}.{annotation.__qualname__}"
    return str(annotation).replace("typing.", "")


def _lambda_source(fn: Callable[..., object]) -> str | None:
    """The body of a lambda as written, or None when it cannot be recovered."""
    try:
        text = inspect.getsource(fn)
    except (OSError, TypeError):
        return None
    start = text.find("lambda")
    for end in range(len(text), start, -1):
        try:
            node = ast.parse(text[start:end].strip(), mode="eval").body
        except SyntaxError:
            continue
        if isinstance(node, ast.Lambda):
            return ast.unparse(node.body)
    return None


def _default(field: FieldInfo) -> str:
    if field.is_required():
        return "required"
    factory = field.default_factory
    if factory is not None:
        name = getattr(factory, "__qualname__", repr(factory))
        body = _lambda_source(factory) if name.endswith("<lambda>") else None
        return f"factory: {body or name}"
    return repr(field.default)


def _import(dotted: str) -> Any:
    module, _, name = dotted.rpartition(".")
    return getattr(importlib.import_module(module), name)


def render_schema(dotted: str) -> str:
    model = _import(dotted)
    if not (isinstance(model, type) and issubclass(model, BaseModel)):
        raise TypeError(f"{dotted} is not a Pydantic model")
    rows = [
        "| Field | Python type | Required / default | Constraints | Meaning |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name, field in model.model_fields.items():
        cells = (
            name,
            _type_name(field.annotation),
            _default(field),
            str(field.metadata),
            field.description or "",
        )
        rows.append("| " + " | ".join(_cell(c) for c in cells) + " |")
    return "\n".join(rows) + "\n"


class _Captured(Exception):
    def __init__(self, parser: argparse.ArgumentParser) -> None:
        super().__init__("parser captured")
        self.parser = parser


def capture_parser(module_name: str) -> argparse.ArgumentParser:
    """The parser a node module's ``main()`` builds, without running the node."""
    main: Callable[[], object] = importlib.import_module(module_name).main

    def intercept(self: argparse.ArgumentParser, *_: object, **__: object) -> object:
        raise _Captured(self)

    with (
        mock.patch.object(argparse.ArgumentParser, "parse_args", intercept),
        mock.patch.object(sys, "argv", [module_name]),
    ):
        try:
            main()
        except _Captured as captured:
            return captured.parser
    raise RuntimeError(f"{module_name}.main() returned without parsing arguments")


_ACTION_NAMES = {
    argparse._StoreTrueAction: "store_true",
    argparse._StoreFalseAction: "store_false",
    argparse._StoreConstAction: "store_const",
    argparse._AppendAction: "append",
    argparse._CountAction: "count",
    argparse.BooleanOptionalAction: "BooleanOptionalAction",
}


def _action_kind(action: argparse.Action) -> str:
    if action.type is not None:
        return getattr(action.type, "__name__", repr(action.type))
    return _ACTION_NAMES.get(type(action), "str")


def render_cli(module_name: str) -> str:
    rows = [
        "| Argument | Type/action | Required | Default | Choices | Help |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for action in capture_parser(module_name)._actions:
        if isinstance(action, argparse._HelpAction):
            continue
        cells = (
            ", ".join(action.option_strings) or action.dest,
            _action_kind(action),
            str(action.required),
            repr(action.default),
            repr(list(action.choices)) if action.choices is not None else "—",
            repr(action.help) if action.help else "—",
        )
        rows.append("| " + " | ".join(_cell(c) for c in cells) + " |")
    return "\n".join(rows) + "\n"


def render_constructor(dotted: str) -> str:
    """``Class(<__init__ arguments without self>)`` as written in the class source."""
    cls = _import(dotted)
    (class_node,) = ast.parse(inspect.getsource(cls)).body
    if not isinstance(class_node, ast.ClassDef):
        raise TypeError(f"{dotted} is not a class")
    init = next(
        (
            node
            for node in class_node.body
            if isinstance(node, ast.FunctionDef) and node.name == "__init__"
        ),
        None,
    )
    if init is None:
        raise ValueError(f"{dotted} defines no __init__ of its own")
    arguments = init.args
    _annotate_computed_defaults(arguments, inspect.signature(cls.__init__).parameters)
    arguments.args = arguments.args[1:]  # drop self
    return f"```text\n{cls.__name__}({ast.unparse(arguments)})\n```\n"


def _annotate_computed_defaults(
    arguments: ast.arguments, values: Mapping[str, inspect.Parameter]
) -> None:
    """Show a computed default with its value: ``VALIDATE.provider (= 'openai')``.

    A source expression alone hides the provider and model a caller actually
    gets; a literal default is left as written.
    """
    positional = arguments.posonlyargs + arguments.args
    pairs = list(
        zip(
            positional[len(positional) - len(arguments.defaults) :], arguments.defaults, strict=True
        )
    )
    pairs += [
        (a, d)
        for a, d in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True)
        if d is not None
    ]
    for index, (arg, node) in enumerate(pairs):
        if isinstance(node, ast.Constant):
            continue
        shown = ast.Name(id=f"{ast.unparse(node)} (= {values[arg.arg].default!r})")
        if index < len(arguments.defaults):
            arguments.defaults[index] = shown
        else:
            position = arguments.kwonlyargs.index(arg)
            arguments.kw_defaults[position] = shown


#: Set in the child process that renders; see :func:`_run_isolated`.
_ISOLATED = "SIDERIUS_REFERENCE_TABLES_ISOLATED"


def _run_isolated(argv: list[str]) -> int:
    """Render in a child whose model and loss plugin discovery sees nothing.

    Some CLI help text lists the model registry, which otherwise includes the
    caller's generated library and checkout-local ``agent_generated/``.
    Pointing both plugin variables at one empty directory makes the output
    depend on this checkout's source only.
    """
    with tempfile.TemporaryDirectory(prefix="siderius-reference-tables-") as empty:
        env = {
            **os.environ,
            "SIDERIUS_PLUGIN_DIRS": empty,
            "SIDERIUS_LOSS_DIRS": empty,
            _ISOLATED: "1",
        }
        command = [sys.executable, "-m", "tools.orchestration_setup.reference_tables", *argv]
        return subprocess.run(command, env=env, check=False).returncode


_RENDERERS: dict[str, Callable[[str], str]] = {
    "schema": render_schema,
    "cli": render_cli,
    "constructor": render_constructor,
}


def regenerate(text: str) -> str:
    """``text`` with every generated region re-rendered from source."""
    return _REGION.sub(lambda m: m["open"] + _RENDERERS[m["kind"]](m["target"]) + m["close"], text)


def payload_files(root: Path) -> list[Path]:
    """Payload reference files that contain at least one generated region."""
    return sorted(
        path
        for path in (root / PAYLOAD_REFERENCES).rglob("*.md")
        if _REGION.search(path.read_text(encoding="utf-8"))
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate the orchestrator-toolkit reference tables from source."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="exit 1 if any region drifted")
    mode.add_argument("--write", action="store_true", help="rewrite drifted regions in place")
    args = parser.parse_args(argv)
    if os.environ.get(_ISOLATED) != "1":
        return _run_isolated(sys.argv[1:] if argv is None else argv)
    root = require_checkout(checkout_root())
    drifted = []
    for path in payload_files(root):
        current = path.read_text(encoding="utf-8")
        fresh = regenerate(current)
        if fresh != current:
            drifted.append(path.relative_to(root))
            if args.write:
                path.write_text(fresh, encoding="utf-8")
    for path in drifted:
        print(("rewrote " if args.write else "drifted ") + str(path))
    return 1 if drifted and args.check else 0


if __name__ == "__main__":
    raise SystemExit(main())
