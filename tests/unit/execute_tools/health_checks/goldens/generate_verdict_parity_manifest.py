#!/usr/bin/env python
"""Generate the Step-08a verdict-parity manifest (capture-first evidence).

Usage (from the repository root, with the project virtualenv)::

    .venv/bin/python tests/unit/execute_tools/health_checks/goldens/\\
        generate_verdict_parity_manifest.py            # write
    .venv/bin/python .../generate_verdict_parity_manifest.py --check  # verify

The manifest freezes what the six TIDMAD health checks produce TODAY, so
every later Step-08a commit compares against evidence the new code did not
author (design §4.1; the D14-1 capture-first lesson).

**Refuses to write from a tree with modified production source.** A
manifest captured after a behavioural edit is not a baseline — it is the
new behaviour wearing a baseline's name. Only the test-side files that
carry the capture itself may differ from HEAD.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.unit.execute_tools.health_checks._verdict_corpus import (  # noqa: E402
    CASE_IDS,
    record_all,
)

MANIFEST_PATH = Path(__file__).resolve().parent / "verdict_parity_manifest_pre08a.json"

_CAPTURE_OWNED = {
    "tests/unit/execute_tools/health_checks/_verdict_corpus.py",
    "tests/unit/execute_tools/health_checks/goldens/generate_verdict_parity_manifest.py",
    "tests/unit/execute_tools/health_checks/goldens/verdict_parity_manifest_pre08a.json",
}
"""The only paths allowed to differ from HEAD when capturing."""


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def _assert_capture_tree_clean() -> str:
    """Return HEAD, after proving no production file is modified."""
    changed = {line for line in _git("diff", "HEAD", "--name-only").splitlines() if line}
    offending = sorted(changed - _CAPTURE_OWNED)
    if offending:
        raise SystemExit(
            "Refusing to capture: production/test files modified relative to "
            f"HEAD: {offending}. Capture the manifest BEFORE the behavioural "
            "change (design §4.1), or use --check to verify an existing one."
        )
    return _git("rev-parse", "HEAD")


def _build(source_tree_sha: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="verdict_parity_") as tmp:
        rows = record_all(Path(tmp))
    return {
        "schema_version": 1,
        "purpose": (
            "Pre-08a capture of the six TIDMAD health checks' HealthCheckResult "
            "fields and the design-§3.1 verdict class each one maps to. Expected "
            "verdicts are transcribed independently in _verdict_corpus."
            "classify_expected_verdict — never read back from production."
        ),
        "design_doc": (
            "docs/design/generic_framework_upgrade/step_08_health_check_task_profile/"
            "pr_08a_check_input_contract.md"
        ),
        "source_tree_sha": source_tree_sha,
        "case_count": len(rows),
        "cases": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Regenerate in memory and diff against the committed manifest.",
    )
    args = parser.parse_args()

    if args.check:
        committed = json.loads(MANIFEST_PATH.read_text())
        regenerated = _build(committed["source_tree_sha"])
        if regenerated == committed:
            print(f"OK — {len(CASE_IDS)} cases reproduce the committed manifest byte-identically.")
            return 0
        print("MISMATCH — regenerated manifest differs from the committed one.")
        for new_row, old_row in zip(regenerated["cases"], committed["cases"], strict=False):
            if new_row != old_row:
                print(f"  first differing case: {old_row['case_id']}")
                break
        return 1

    sha = _assert_capture_tree_clean()
    manifest = _build(sha)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(
        f"Wrote {MANIFEST_PATH.relative_to(REPO_ROOT)} — {manifest['case_count']} cases at {sha}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
