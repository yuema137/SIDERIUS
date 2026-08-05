#!/usr/bin/env python
"""Refuse an operator value that is not safe as a path component.

    python scripts/validate_path_component.py --value <v> [--kind <what>]
    -> exit 0, nothing on stdout
    -> exit 2, the reason on stderr

The shared rule lives in `core.campaign_identity.validate_path_component`
and is reached from here so a shell caller does not need a second copy of
it. A second copy of a security rule is how the two drift: one of them
eventually learns about `..` and the other does not.

`--kind` appears only in the refusal message, so an operator is told
which knob to fix rather than being handed a bare value.
"""

from __future__ import annotations

import argparse
import sys

from core.campaign_identity import PathComponentError, validate_path_component


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # NOT `required=True` with a positional fallback: an empty value is a
    # value this tool must be able to refuse, and `--value ""` is how a
    # shell passes one.
    parser.add_argument("--value", required=True)
    parser.add_argument("--kind", default="identifier")
    args = parser.parse_args(argv)

    try:
        validate_path_component(args.value, kind=args.kind)
    except PathComponentError as exc:
        print(f"validate_path_component: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
