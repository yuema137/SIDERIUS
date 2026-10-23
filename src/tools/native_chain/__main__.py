"""Public native-chain review command."""

import argparse
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
        review(request)
    except (ValueError, OSError, RuntimeError) as error:
        from tools.native_chain.models import NativeChainRefusal

        reason = str(error) if isinstance(error, NativeChainRefusal) else "review_input_refused"
        print(f"Native chain refused: {reason}", file=sys.stderr)
        return 78
    print("Native chain capture published.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
