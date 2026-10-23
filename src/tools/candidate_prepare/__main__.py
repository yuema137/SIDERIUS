"""Prepare an offline native candidate bundle from explicit selections."""

import argparse
from pathlib import Path

from . import (
    CandidatePreparationRequest,
    ReusableCandidatePreparationRequest,
    prepare_candidate,
    prepare_reusable_candidate,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    choices = parser.add_mutually_exclusive_group(required=True)
    choices.add_argument("--request", type=Path)
    choices.add_argument("--reusable-request", type=Path)
    args = parser.parse_args()
    if args.reusable_request:
        receipt = prepare_reusable_candidate(
            ReusableCandidatePreparationRequest.model_validate_json(
                args.reusable_request.read_bytes()
            )
        )
    else:
        receipt = prepare_candidate(
            CandidatePreparationRequest.model_validate_json(args.request.read_bytes())
        )
    print(receipt.model_dump_json(indent=2))
    return 0 if receipt.status == "prepared" else 1


if __name__ == "__main__":
    raise SystemExit(main())
