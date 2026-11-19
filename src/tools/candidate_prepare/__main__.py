"""Prepare an offline native candidate bundle from explicit selections."""

import argparse
import sys
from pathlib import Path

from tools.candidate_worker.models import CandidateRunRequest

from . import (
    CandidatePreparationReceipt,
    CandidatePreparationRequest,
    ReusableCandidatePreparationRequest,
    ReusablePreparationReceipt,
    prepare_candidate,
    prepare_reusable_candidate,
    prepared_gpu_warning,
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
    return finish(receipt)


def finish(receipt: CandidatePreparationReceipt | ReusablePreparationReceipt) -> int:
    """Print the receipt on stdout and the issue #1562 advisory, if any, on stderr.

    The exit status depends on the receipt status only: the advisory never fails
    preparation, and stdout stays the receipt JSON alone.
    """
    print(receipt.model_dump_json(indent=2))
    if receipt.status != "prepared":
        return 1
    if receipt.candidate_request_path is not None:
        request = CandidateRunRequest.model_validate_json(
            Path(receipt.candidate_request_path).read_bytes()
        )
        warning = prepared_gpu_warning(request)
        if warning is not None:
            print(f"Warning: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
