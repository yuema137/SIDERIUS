"""Prepare an offline native candidate bundle from explicit selections."""

import argparse
from pathlib import Path

from . import CandidatePreparationRequest, prepare_candidate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    args = parser.parse_args()
    receipt = prepare_candidate(
        CandidatePreparationRequest.model_validate_json(args.request.read_bytes())
    )
    print(receipt.model_dump_json(indent=2))
    return 0 if receipt.status == "prepared" else 1


if __name__ == "__main__":
    raise SystemExit(main())
