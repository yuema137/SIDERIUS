"""Step 12 / PR-12bc — the §F B→C checkpoint's two censuses, made permanent.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12bc_generic_task_boundary_closure.md`` §F items 8 and 9; ledger §Q.F.

The §F checkpoint is a one-time gate between the phases, but two of its ten
proofs are properties that must keep holding for the rest of the PR — and for
everything after it. A checkpoint verified once and never again is a claim,
not a guard, so both are censuses here:

* **item 9** — no hidden task/scope identity dispatch was introduced.
"""

from __future__ import annotations

import ast
import pathlib
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def _production_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "*.py"], cwd=REPO_ROOT, capture_output=True, text=True
    ).stdout.split()
    return [f for f in out if not f.startswith("tests/")]


#: The generic framework tree. Real-task modules live outside this repository,
#: so no production exclusion list is needed.
#: **F-12bc-9** — `execute_tools/` was missing here, and the omission was
#: self-evidencing: `TASK_OWNED` below exempts three `execute_tools/` files,
#: and those exemptions could never fire, because nothing under that directory
#: was ever scanned. An exclusion list that cannot exclude anything is a
#: statement about what the author meant to scan.
#:
#: It matters more than a coverage gap. `execute_tools/` is where the scope ABI
#: lives — `scope_artifact.py`, `task_data_path.py` — so the single most
#: important generic surface in this PR was the one this census could not see.
#: Found at BC-FINAL by planting `"tidmad_scope_v1"` into `scope_artifact.py`
#: and watching every census stay green.
#:
#: The landed tree is clean under the wider scope: 52 additional files, zero
#: offenders in all three checks. Nothing is exempted to make that true.
GENERIC_PREFIXES = ("core/", "workflows/", "nodes/", "agent/", "execute_tools/")
TASK_NAMES = {"tidmad", "oxford_iiit_pet", "davis_future_prediction", "pets", "davis"}


class TestItem9NoHiddenTaskOrScopeIdentityDispatch:
    def test_no_generic_module_compares_against_a_task_name(self):
        offenders: list[str] = []
        for rel in _production_files():
            if not rel.startswith(GENERIC_PREFIXES):
                continue
            tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Compare):
                    for comparator in node.comparators:
                        if isinstance(comparator, ast.Constant) and comparator.value in TASK_NAMES:
                            offenders.append(f"{rel}:{node.lineno}")
        assert offenders == [], (
            f"{offenders} branch on a TASK NAME. Discrimination is by "
            f"composition PRESENCE or by what the task DECLARES — never by "
            f"who the task is."
        )

    def test_no_central_task_mapping_table_exists(self):
        """The `{"tidmad": ..., "pets": ...}` catalog, forbidden by
        construction. A dict LITERAL keyed by two or more task names is a
        central catalog however it is spelled.
        """
        offenders: list[str] = []
        for rel in _production_files():
            if not rel.startswith(GENERIC_PREFIXES):
                continue
            tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Dict):
                    keys = {
                        k.value
                        for k in node.keys
                        if isinstance(k, ast.Constant) and isinstance(k.value, str)
                    }
                    if len(keys & TASK_NAMES) >= 2:
                        offenders.append(f"{rel}:{node.lineno}")
        assert offenders == [], f"{offenders} declare a central task mapping table."

    def test_no_scope_kind_dispatch_in_generic_core(self):
        """Each task's payload is self-identifying so IT can refuse a foreign
        one. The FRAMEWORK must never branch on that tag — doing so would make
        the transport aware of the shapes it exists to stay ignorant of.
        """
        offenders: list[str] = []
        for rel in _production_files():
            if not rel.startswith(GENERIC_PREFIXES):
                continue
            src = (REPO_ROOT / rel).read_text(encoding="utf-8")
            for kind in ("tidmad_scope_v1", "pets_scope_v1", "davis_scope_v1"):
                if kind in src:
                    offenders.append(f"{rel}: {kind}")
        assert offenders == [], f"{offenders} name a scope KIND in generic core."

    def test_the_scope_transport_never_inspects_a_payload(self):
        """The ABI's own opacity, re-asserted at the checkpoint: the framework
        handles bytes and a hash.
        """
        tree = ast.parse(
            (REPO_ROOT / "execute_tools" / "scope_artifact.py").read_text(encoding="utf-8")
        )
        called = {
            n.func.attr
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        assert "loads" not in called and "load" not in called


@pytest.mark.parametrize(
    ("rel", "needle", "label"),
    [
        (
            "workflows/task_composition.py",
            "if declared in registered_task_data_path_ids():",
            "F-12-3 early return",
        ),
        (
            "execute_tools/task_data_path.py",
            "_REGISTRY: dict[str, TaskDataPath] = {}",
            "the registry",
        ),
        (
            "execute_tools/task_data_path.py",
            "is already registered with DIFFERENT",
            "duplicate refusal (C1: two-phase — identical content is idempotent)",
        ),
        (
            "tests/unit/workflows/test_step10_p1_c1_composition.py",
            "def test_recomposing_in_one_process_yields_the_REGISTERED_object",
            "F-12bc-3 pinning test",
        ),
        (
            "tests/unit/guardrails/test_task_data_path_census.py",
            "def test_task_implementation_imports_on_the_surface_are_the_declared_set",
            "F-12bc-4 bootstrap census",
        ),
    ],
)
def test_item10_phase_c_anchors_still_exist(rel, needle, label):
    """§F item 10 — Phase C's assumptions, re-audited against the ACTUAL
    Phase-B implementation rather than against pre-B source.

    Anchored on CONTENT, not line numbers: Phase B moved several of these
    (the registry went from `:219` to `:570` as `task_data_path.py` grew), and
    a line-number assertion would fail for a reason that has nothing to do
    with the property.
    """
    assert needle in (REPO_ROOT / rel).read_text(encoding="utf-8"), (
        f"{label} is gone from {rel} — Phase C's plan assumes it is there."
    )
