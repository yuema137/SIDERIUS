"""Write an optional local JSON/HTML report without starting a workflow."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.durable_io import publish_bytes_write_once
from tools.setup_review.inspection import inspect_declaration
from tools.setup_review.models import SetupReviewRequest
from tools.setup_review.render import render_html


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True, help="Setup request JSON file")
    parser.add_argument("--output", type=Path, required=True, help="New absolute report directory")
    args = parser.parse_args(argv)
    try:
        request = SetupReviewRequest.model_validate_json(args.request.read_bytes())
        report = inspect_declaration(request, args.output)
        payloads = {
            "report.json": (report.model_dump_json(indent=2) + "\n").encode("utf-8"),
            "index.html": render_html(report).encode("utf-8"),
        }
        output = Path(report.output_directory)
        output.mkdir(mode=0o700)
        # Each file is atomic and write-once. An interrupted pair stays visible
        # for diagnosis; cleanup cannot safely distinguish a concurrent writer's
        # replacement from our own file, so never delete report contents here.
        for name, payload in payloads.items():
            publish_bytes_write_once(str(output / name), payload)
    except (OSError, ValueError) as exc:
        print(f"Setup declaration inspection failed: {exc}", file=sys.stderr)
        return 2
    print(f"Declaration report: {output / 'report.json'}")
    print(f"Open locally: {output / 'index.html'}")
    print("No experiment or LLM review ran; launch readiness is not verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
