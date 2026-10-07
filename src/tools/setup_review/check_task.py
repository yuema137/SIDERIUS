"""Explicitly compose trusted task code in a bounded, offline sandbox."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tools.setup_review.composition_check import check_task
from tools.setup_review.composition_models import TaskCheckRequest, TaskCheckSettings
from tools.setup_review.models import SetupReviewRequest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--request", type=Path, required=True, help="Existing standard setup request JSON"
    )
    parser.add_argument(
        "--read-only",
        type=Path,
        action="append",
        default=[],
        help="Explicit task/config/provider source root; repeat as needed",
    )
    parser.add_argument(
        "--scratch", type=Path, required=True, help="New canonical absolute check scratch directory"
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="New canonical absolute report directory"
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        required=True,
        help="Positive finite wall-clock budget for this child check",
    )
    parser.add_argument(
        "--result-max-bytes",
        type=int,
        default=TaskCheckSettings.model_fields["result_max_bytes"].default,
        help="Positive child-result JSON size limit (default: %(default)s); not a memory/disk quota",
    )
    args = parser.parse_args(argv)
    try:
        request = TaskCheckRequest(
            setup=SetupReviewRequest.model_validate_json(args.request.read_bytes()),
            scratch=args.scratch,
            output=args.output,
            read_only=tuple(args.read_only),
            settings=TaskCheckSettings(
                timeout_seconds=args.timeout_seconds, result_max_bytes=args.result_max_bytes
            ),
        )
        report = check_task(request)
    except (OSError, ValueError) as error:
        print(f"Task composition check failed: {error}", file=sys.stderr)
        return 2
    print(f"Task composition check {report.result.outcome}: {request.output / 'index.html'}")
    return 0 if report.result.outcome == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
