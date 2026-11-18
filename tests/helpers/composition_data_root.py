"""A real directory for tests that bind a composition (Step 11 C4).

``bind_run_task_composition`` requires ``physical_data_root`` for a
composed run and refuses with ``CompositionDataRootMissing`` without it:
the framework has no default data root. That fail-closed contract is the
point, so tests must state a root like production does rather than the
production function growing a default.

The tests that use this are not testing the data root; they compose in
order to exercise something else. They need *a real, existing directory*
and nothing more.

**Derived from the checkout, never hardcoded** — the repository-portability
rule. A test must not resolve a path belonging to another clone, and a
fixed absolute path would keep resolving on the machine that has one while
failing on CI.
"""

from __future__ import annotations

from pathlib import Path

#: The current checkout's root: guaranteed to exist and to be a directory,
#: and belonging to the checkout the test is actually running in.
COMPOSED_TEST_DATA_ROOT: str = str(Path(__file__).resolve().parents[2])
