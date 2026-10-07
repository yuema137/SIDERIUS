"""Install orchestration instructions in an explicitly configured external project."""

import argparse
import subprocess
import sys
from pathlib import Path

from tools.orchestration_setup.assembly import assemble


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True, help="explicit SandboxProfile JSON")
    parser.add_argument(
        "--run-declaration", type=Path, required=True, help="user-authored Markdown"
    )
    args = parser.parse_args(argv)
    try:
        receipt = assemble(args.profile, args.run_declaration)
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"orchestration assembly refused: {exc}", file=sys.stderr)
        return 2
    print(receipt.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
