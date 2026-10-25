"""Native writer transport and read-only inspection; no force-unlock command."""

import argparse
import fcntl
import os
import sys
from pathlib import Path

from .launch import launch_shell
from .models import WriterRefusal
from .ownership import TRANSPORT_ENV, inherit, inspect_writer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("launch", "check", "release-submission", "inspect"))
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--capture-sha256")
    supplied = list(sys.argv[1:] if argv is None else argv)
    boundary = supplied.index("--") if "--" in supplied else len(supplied)
    args = parser.parse_args(supplied[:boundary])
    command = supplied[boundary + 1 :]
    try:
        if args.command == "inspect":
            print(inspect_writer(args.workspace).model_dump_json())
            return 0
        if args.command == "launch":
            if not command:
                raise WriterRefusal("writer_command_required")
            return launch_shell(args.workspace, command, capture_sha256=args.capture_sha256)
        payload = os.environ.get(TRANSPORT_ENV)
        if payload is None:
            raise WriterRefusal("writer_transport_missing")
        lease = inherit(args.workspace, payload)
        try:
            if args.command == "release-submission":
                if lease.claim is not None:
                    raise WriterRefusal("registered_slurm_unsupported")
                # Same open description as the submitter: release before sbatch
                # can run a compute job which cannot inherit this descriptor.
                fcntl.flock(lease.fd, fcntl.LOCK_UN)
        finally:
            lease.close(clean=True)
    except (OSError, ValueError, WriterRefusal) as error:
        reason = str(error) if isinstance(error, WriterRefusal) else "writer_state_refused"
        print(f"Native writer refused: {reason}", file=sys.stderr)
        return 78
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
