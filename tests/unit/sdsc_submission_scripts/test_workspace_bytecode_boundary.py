"""Regression coverage for workspace-owned execution state.

External consumers import SIDERIUS from a source checkout.  A synchronized
four-task qualification at framework ``3eb8fc67`` left five ignored ``.pyc``
files in that checkout even though every declared run artifact was correctly
workspace-owned.  These tests protect the two supported launch boundaries:
the chain wrapper before its source-authority probe, and the direct
one-iteration Python entry point before any framework import.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUN_CHAIN = REPO_ROOT / "sdsc_submission_scripts" / "run_chain.sh"
RUN_ONE = REPO_ROOT / "sdsc_submission_scripts" / "run_one_iteration.py"


def test_chain_exports_no_bytecode_policy_before_every_python_call(tmp_path: Path) -> None:
    """Catch the shell entry point invoking Python before checkout writes are disabled.

    The exact-checkout environment contract intentionally ignores a foreign
    activated interpreter, so this boundary is checked by source ordering.
    Removing or moving the export after either Python-bearing launch step
    fails the assertion.
    """
    del tmp_path
    source = RUN_CHAIN.read_text(encoding="utf-8")
    policy = source.index("export PYTHONDONTWRITEBYTECODE=1")
    assert policy < source.index("resolve_py_cmd\n")
    assert policy < source.index("enforce_source_tree_authority\n")


def test_direct_iteration_disables_bytecode_before_framework_imports() -> None:
    """Catch direct invocation importing SIDERIUS before setting its policy.

    ``run_one_iteration.py`` is a supported entry point independent of the
    shell chain.  The textual ordering assertion is intentional: importing
    the module to test the setting would execute the very framework imports
    whose order is under test.
    """
    source = RUN_ONE.read_text(encoding="utf-8")
    policy_env = source.index('os.environ["PYTHONDONTWRITEBYTECODE"] = "1"')
    policy_runtime = source.index("sys.dont_write_bytecode = True")
    first_framework_import = min(
        source.index("from agent."),
        source.index("from core."),
        source.index("from execute_tools."),
        source.index("from workflows."),
    )

    assert policy_env < first_framework_import
    assert policy_runtime < first_framework_import
