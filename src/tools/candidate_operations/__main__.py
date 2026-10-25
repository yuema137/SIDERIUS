"""Thin JSON CLI over the same local submission/read functions used by Python."""

import argparse
import os
import sys
from pathlib import Path
from uuid import UUID

from .files import read_bytes
from .logs import read_operation_log
from .models import (
    SUBMISSION,
    LogReadRequest,
    OperationError,
    OperationFailure,
    OperationStoreConfig,
)
from .native_chain import review_native_chain_operation
from .read import read_operation
from .submit import submit_operation


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Submit or inspect one detached native candidate operation"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("submit", "review", "status", "log"):
        command = commands.add_parser(name)
        command.add_argument("--store-config", required=True)
        if name in {"submit", "review"}:
            command.add_argument("--request", required=True)
        else:
            command.add_argument("--operation-id", required=True)
        if name == "log":
            command.add_argument("--kind", choices=("native", "operation"), required=True)
            command.add_argument("--offset", type=int, default=0)
            command.add_argument("--limit", type=int, default=65536)
    args = parser.parse_args()
    try:
        config = OperationStoreConfig.model_validate_json(
            read_bytes(Path(args.store_config).absolute())
        )
        if args.command in {"submit", "review"}:
            submission = SUBMISSION.validate_json(read_bytes(Path(args.request).absolute()))
            if args.command == "review":
                if submission.kind != "native_chain":
                    raise OperationFailure("kind", "review requires native_chain")
                result = review_native_chain_operation(
                    config, submission, launch_environment=os.environ
                )
            else:
                result = submit_operation(config, submission, launch_environment=os.environ)
        elif args.command == "status":
            result = read_operation(config, UUID(args.operation_id))
        else:
            result = read_operation_log(
                config,
                LogReadRequest(
                    operation_id=UUID(args.operation_id),
                    kind=args.kind,
                    offset=args.offset,
                    max_bytes=args.limit,
                ),
            )
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
