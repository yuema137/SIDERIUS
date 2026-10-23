"""Public native-chain review command."""

import argparse
import hashlib
import shlex
import subprocess
import sys
from pathlib import Path

from tools.native_chain.models import NativeChainReviewRequest
from tools.native_chain.review import read_bytes, review


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("review",))
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args()
    try:
        # The envelope itself has a fixed transport ceiling before its own limit is known.
        request = NativeChainReviewRequest.model_validate_json(read_bytes(args.request, 1048576))
        capture = review(request)
    except (
        ValueError,
        OSError,
        RuntimeError,
        subprocess.TimeoutExpired,
        subprocess.CalledProcessError,
    ) as error:
        from tools.native_chain.models import NativeChainRefusal

        reason = str(error) if isinstance(error, NativeChainRefusal) else "review_input_refused"
        print(f"Native chain refused: {reason}", file=sys.stderr)
        return 78
    path = request.output / "capture.json"
    digest = hashlib.sha256(read_bytes(path, request.input_max_bytes)).hexdigest()
    print("Native chain capture published. Run this command from the same checkout:")
    print(
        shlex.join(
            [
                "bash",
                "scripts/launch/run_chain.sh",
                *capture.shell_argv,
                "--expected_chain_capture",
                str(path),
                "--expected_chain_capture_sha256",
                digest,
                "--chain_capture_input_max_bytes",
                str(request.input_max_bytes),
            ]
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
