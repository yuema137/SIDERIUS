"""Explicit local hardware/profile observation after a saved task-settings check."""

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from execute_tools.data_paths import DatasetDirectoryUnavailable
from tools.setup_review.environment_models import EnvironmentPreviewRequest
from tools.setup_review.environment_settings import inspect_environment
from tools.setup_review.semantic_models import SnapshotInputError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report", type=Path, required=True, help="Absolute saved task report.json"
    )
    parser.add_argument(
        "--expected-sha256", required=True, help="SHA-256 of that report's exact bytes"
    )
    parser.add_argument("--output", type=Path, required=True, help="New external report directory")
    parser.add_argument(
        "--input-max-bytes",
        type=int,
        default=1048576,
        help="Maximum saved-report bytes (default: 1 MiB)",
    )
    parser.add_argument(
        "--check-environment",
        action="store_true",
        help="Check configured credential names for presence; never record values",
    )
    parser.add_argument(
        "--bind-launch",
        action="store_true",
        help="Explicitly pin selected files and a clean installation for optional reviewed launch",
    )
    args = parser.parse_args(argv)
    try:
        request = EnvironmentPreviewRequest.model_validate(vars(args))
        inspect_environment(request)
    except SnapshotInputError as error:
        print(f"Environment preview refused: {error}", file=sys.stderr)
        return 2
    except DatasetDirectoryUnavailable:
        print(
            "Environment preview refused: the selected data directory does not exist or is not "
            "a directory. Set --data_dir to an existing directory in the original launch arguments "
            "and regenerate the task check.",
            file=sys.stderr,
        )
        return 2
    except (
        ValidationError,
        OSError,
        ValueError,
        TimeoutError,
        RuntimeError,
    ) as error:
        print(
            f"Environment preview refused ({type(error).__name__}). Check the report digest/size, "
            "saved working directory, current inputs and environment; choose a new output directory. "
            "No launch was approved. Supplied values are omitted.",
            file=sys.stderr,
        )
        return 2
    print(f"Environment settings observed: {request.output / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
