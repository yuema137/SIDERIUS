"""Explicit semantic review or skip of a saved standard setup snapshot."""

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from tools.setup_review.semantic_models import SemanticReviewRequest, SnapshotInputError
from tools.setup_review.semantic_review import review_snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--request", type=Path, required=True, help="Typed review/skip operation JSON"
    )
    args = parser.parse_args(argv)
    try:
        request = SemanticReviewRequest.model_validate_json(args.request.read_bytes())
        receipt = review_snapshot(request)
    except SnapshotInputError as error:
        print(f"Setup review refused: {error}", file=sys.stderr)
        return 2
    except ValidationError as error:
        fields = [".".join(str(part) for part in item["loc"]) for item in error.errors()]
        print(
            "Setup review request/report fields are invalid: "
            + ", ".join(fields)[:512]
            + ". Check the typed contract; values are omitted.",
            file=sys.stderr,
        )
        return 2
    except (OSError, ValueError, TimeoutError) as error:
        # Validation errors may echo supplied values; do not print arbitrary request contents.
        print(
            f"Setup review refused ({type(error).__name__}). Check the request schema, report "
            "digest/size, paths and limits; choose a new output directory.",
            file=sys.stderr,
        )
        return 2
    print(f"Setup review {receipt.outcome}: {request.operation.output / 'index.html'}")
    return 2 if receipt.outcome == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
