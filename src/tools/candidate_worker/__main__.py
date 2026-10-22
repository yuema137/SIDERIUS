"""Synchronous JSON CLI for the same Python launch boundary."""

import argparse
from pathlib import Path

from .launch import launch_candidate
from .models import CandidateRunRequest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    args = parser.parse_args()
    receipt = launch_candidate(CandidateRunRequest.model_validate_json(args.request.read_bytes()))
    print(receipt.model_dump_json(indent=2))
    return 0 if receipt.status in {"accepted", "rejected"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
