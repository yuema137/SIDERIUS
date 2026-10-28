"""``python -m tools.adaptors`` entrypoint."""

from __future__ import annotations

import sys

from tools.adaptors.cli import main

if __name__ == "__main__":
    sys.exit(main())
