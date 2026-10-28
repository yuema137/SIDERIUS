"""Thin JSON CLI over the same local submission/read functions used by Python."""

import argparse
import os
import sys
from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel

from core.durable_io import publish_bytes_write_once

from .files import encode, read_bytes
from .logs import read_operation_log
from .loop_resume import request_loop_pause, review_loop_resume
from .models import (
    SUBMISSION,
    CandidateLoopResumeOperation,
    CandidateLoopResumeRequest,
    LogReadRequest,
    OperationError,
    OperationFailure,
    OperationStoreConfig,
)
from .native_chain import review_native_chain_operation
from .native_resume import review_native_chain_resume
from .read import read_operation
from .submit import request_loop_stop, submit_operation
from .tokens import read_operation_tokens

REQUEST_COMMANDS = ("submit", "review")
OPERATION_COMMANDS = (
    "review-resume",
    "status",
    "log",
    "tokens",
    "stop-loop",
    "pause-loop",
    "review-loop-resume",
    "write-loop-resume",
)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Submit or inspect one detached native candidate operation"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in (*REQUEST_COMMANDS, *OPERATION_COMMANDS):
        command = commands.add_parser(name)
        command.add_argument("--store-config", required=True)
        if name in REQUEST_COMMANDS:
            command.add_argument("--request", required=True)
        else:
            command.add_argument("--operation-id", required=True)
        if name == "log":
            command.add_argument("--kind", choices=("native", "operation"), required=True)
            command.add_argument("--offset", type=int, default=0)
            command.add_argument("--limit", type=int, default=65536)
        if name == "write-loop-resume":
            command.add_argument("--output", required=True)
    return parser.parse_args()


def run_request(config: OperationStoreConfig, args: argparse.Namespace) -> BaseModel:
    submission = SUBMISSION.validate_json(read_bytes(Path(args.request).absolute()))
    if args.command == "submit":
        return submit_operation(config, submission, launch_environment=os.environ)
    if submission.kind != "native_chain":
        raise OperationFailure("kind", "review requires native_chain")
    return review_native_chain_operation(config, submission, launch_environment=os.environ)


def read_log(config: OperationStoreConfig, args: argparse.Namespace) -> BaseModel:
    return read_operation_log(
        config,
        LogReadRequest(
            operation_id=UUID(args.operation_id),
            kind=args.kind,
            offset=args.offset,
            max_bytes=args.limit,
        ),
    )


def write_loop_resume(
    config: OperationStoreConfig, args: argparse.Namespace
) -> CandidateLoopResumeOperation:
    """Review one paused authored-loop segment and save its Resume request; never launch.

    The file is created once so a lost-response retry resubmits the same request ID.
    """
    predecessor = UUID(args.operation_id)
    review = review_loop_resume(config, predecessor)
    if review.receipt_digest is None:
        raise OperationFailure("integrity", "reviewed paused segment has no receipt digest")
    operation = CandidateLoopResumeOperation(
        request_id=uuid4(),
        request=CandidateLoopResumeRequest(
            predecessor_operation_id=predecessor,
            expected_receipt_digest=review.receipt_digest,
        ),
    )
    try:
        publish_bytes_write_once(str(Path(args.output).absolute()), encode(operation))
    except FileExistsError as error:
        raise OperationFailure(
            "output_exists", "resume request file already exists; submit it unchanged"
        ) from error
    return operation


OperationCommand = Callable[[OperationStoreConfig, argparse.Namespace], BaseModel]
OPERATION_HANDLERS: dict[str, OperationCommand] = {
    "review-resume": lambda config, args: review_native_chain_resume(
        config, UUID(args.operation_id)
    ),
    "status": lambda config, args: read_operation(config, UUID(args.operation_id)),
    "log": read_log,
    "tokens": lambda config, args: read_operation_tokens(config, UUID(args.operation_id)),
    "stop-loop": lambda config, args: request_loop_stop(config, UUID(args.operation_id)),
    "pause-loop": lambda config, args: request_loop_pause(config, UUID(args.operation_id)),
    "review-loop-resume": lambda config, args: review_loop_resume(config, UUID(args.operation_id)),
    "write-loop-resume": write_loop_resume,
}


def main() -> int:
    args = parse_arguments()
    try:
        config = OperationStoreConfig.model_validate_json(
            read_bytes(Path(args.store_config).absolute())
        )
        if args.command in REQUEST_COMMANDS:
            result = run_request(config, args)
        else:
            result = OPERATION_HANDLERS[args.command](config, args)
        print(result.model_dump_json())
        return 0
    except OperationFailure as error:
        print(error.detail.model_dump_json(), file=sys.stderr)
    except (OSError, ValueError):
        # Pydantic/native diagnostics may contain supplied profile/advice content.
        print(
            OperationError(
                code="invalid_input_or_record",
                message="cannot validate or read the selected operation input/record",
            ).model_dump_json(),
            file=sys.stderr,
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
