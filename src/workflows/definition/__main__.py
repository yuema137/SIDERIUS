"""Offline declaration conversion: bounded input file to completed stdout content."""

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from .models import WorkflowDocument
from .source import (
    MAX_INPUT_BYTES,
    SourceDiagnostic,
    WorkflowSourceError,
    _validation_error,
    parse_workflow_source,
    render_workflow_source,
)


def _read_input(path: Path) -> str:
    with path.open("rb") as stream:
        content = stream.read(MAX_INPUT_BYTES + 1)
    if len(content) > MAX_INPUT_BYTES:
        raise WorkflowSourceError(
            (SourceDiagnostic(code="limit", message="Input exceeds the 1 MiB byte limit"),)
        )
    return content.decode("utf-8")


def _convert(command: str, content: str) -> str:
    if command == "to-json":
        return parse_workflow_source(content).model_dump_json(indent=2) + "\n"
    try:
        document = WorkflowDocument.model_validate_json(content)
    except ValidationError as error:
        _validation_error(error)
    return render_workflow_source(document)


def _describe(diagnostic: SourceDiagnostic) -> str:
    location = ""
    if diagnostic.line is not None:
        location = f" at {diagnostic.line}:{diagnostic.column}"
    field = ""
    if diagnostic.field_path:
        field = " [" + ".".join(str(part) for part in diagnostic.field_path) + "]"
    return f"{diagnostic.code}{location}{field}: {diagnostic.message}"


def main(argv: list[str] | None = None) -> int:
    """Print completed conversion only; errors never emit converted bytes."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("to-json", "Convert a restricted Python declaration to document JSON"),
        ("to-python", "Convert document JSON to canonical Python declaration source"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--input", required=True, type=Path, help="Explicit UTF-8 input file")
    arguments = parser.parse_args(argv)
    try:
        converted = _convert(arguments.command, _read_input(arguments.input))
    except WorkflowSourceError as error:
        for diagnostic in error.diagnostics:
            print(_describe(diagnostic), file=sys.stderr)
        return 2
    except UnicodeDecodeError:
        print("encoding: Input must be UTF-8", file=sys.stderr)
        return 2
    except OSError:
        print("io: Cannot read input file", file=sys.stderr)
        return 2
    sys.stdout.write(converted)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
