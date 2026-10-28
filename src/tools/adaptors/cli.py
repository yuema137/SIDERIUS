"""Agent-runnable custom adaptor commands.

    python -m tools.adaptors inspect   --manifest PATH
    python -m tools.adaptors self-test --manifest PATH
    python -m tools.adaptors admit     --manifest PATH --project DIR

``inspect`` validates the manifest and captures members without executing
them. ``self-test`` runs every fixture twice in supervised children. ``admit``
self-tests, then writes ``DIR/.siderius/adaptors/<id>/<identity>.admission.json``.
Each prints one JSON document on stdout. Exit 0 on success, 2 with a
``[<reason>]`` diagnostic on stderr otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from workflows.custom_adaptors.admission import admission_path, write_admission
from workflows.custom_adaptors.errors import CustomAdaptorError
from workflows.custom_adaptors.manifest import LoadedAdaptor, load_adaptor
from workflows.custom_adaptors.self_test import SelfTestReport, run_self_test

EXIT_OK = 0
EXIT_DIAGNOSTIC = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.adaptors",
        description="Inspect, self-test and admit a custom adaptor from an external project.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name, text in (
        ("inspect", "validate the manifest and print identity and contracts; runs no code"),
        ("self-test", "run every fixture twice in supervised children"),
        ("admit", "self-test, then write the admission record into --project"),
    ):
        command = commands.add_parser(name, help=text)
        command.add_argument("--manifest", type=Path, required=True)
        if name == "admit":
            command.add_argument("--project", type=Path, required=True)
    return parser


def _inspection(loaded: LoadedAdaptor) -> dict[str, object]:
    manifest = loaded.manifest
    return {
        "id": manifest.id,
        "version": manifest.version,
        "role": manifest.role,
        "deterministic": manifest.deterministic,
        "identity_sha256": loaded.identity_sha256,
        "manifest_sha256": manifest.digest,
        "members": [pin.model_dump() for pin in loaded.package.identity.members],
        "inputs": [port.model_dump() for port in manifest.inputs],
        "output": manifest.output.model_dump(),
    }


def _self_test(loaded: LoadedAdaptor) -> SelfTestReport:
    with tempfile.TemporaryDirectory(prefix="siderius-adaptor-") as control:
        return run_self_test(loaded, Path(control))


def _run(args: argparse.Namespace) -> dict[str, object]:
    loaded = load_adaptor(args.manifest)
    if args.command == "inspect":
        return _inspection(loaded)
    if args.command == "admit":
        admission_path(args.project, loaded)  # Refuse a framework location before running code.
    report = _self_test(loaded)
    if args.command == "self-test":
        return report.model_dump(mode="json")
    path = write_admission(args.project, loaded, report)
    return {"admission": str(path), **report.model_dump(mode="json")}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = _run(args)
    except CustomAdaptorError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_DIAGNOSTIC
    print(json.dumps(payload, indent=2, sort_keys=True))
    return EXIT_OK
