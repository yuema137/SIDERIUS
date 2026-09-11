"""``python -m tools.run_report`` — the frozen entrypoint (§V.2, §V.15)."""

from __future__ import annotations

import sys

from tools.run_report.cli import main

if __name__ == "__main__":
    sys.exit(main())
