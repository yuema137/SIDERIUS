"""Step 09.5a C5 — the closing structural censuses (design §33 C and F).

Two properties that no behavioural test can see, because in both cases the
program would still produce identical results:

* **C** — a compatibility wrapper re-exposing the old 99-argument surface. The
  frozen design forbids one in so many words: keeping the old signature alive
  would preserve, verbatim, the structural debt this milestone exists to
  remove, while every test stayed green.
* **F** — a task name entering the new structural surface. Step 12 must be able
  to bind a fourth, out-of-tree task through these carriers; a `tidmad` /
  `pets` / `davis` branch in one of them is the first step to a per-task
  workflow, and nothing would fail today.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The structural surface Step 09.5a created or reshaped. Task identity must
#: not appear in any of it.
NEW_STRUCTURAL_SURFACE = (
    "src/core/chain_state.py",
    "src/core/committed_digests.py",
    "src/workflows/run_bindings.py",
    "src/workflows/run_config.py",
    "src/workflows/strategy_modes.py",
    "src/workflows/tuner_preparation.py",
)

TASK_NAMES = ("tidmad", "pets", "davis", "oxford")


class TestNoTaskIdentityInTheNewSurface:
    @pytest.mark.parametrize("rel", NEW_STRUCTURAL_SURFACE)
    def test_no_task_name_appears_in_executed_code(self, rel):
        """Step 12 must bind a fourth task through these carriers unchanged.

        Docstrings and comments may name a task as an example; executed code
        may not, because that is where a per-task branch would live.
        """
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
        docstrings = {
            id(n.body[0].value)
            for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef))
            and n.body
            and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Constant)
            and isinstance(n.body[0].value.value, str)
        }
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in docstrings:
                    continue
                for task in TASK_NAMES:
                    if task in node.value.lower():
                        offenders.append(f"{rel}:{node.lineno} {node.value[:60]!r}")
            if isinstance(node, ast.Name) and any(t in node.id.lower() for t in TASK_NAMES):
                offenders.append(f"{rel}:{node.lineno} name {node.id}")
        assert not offenders, offenders

    def test_the_scanned_surface_is_not_empty(self):
        """A renamed file would otherwise make this census vacuous."""
        for rel in NEW_STRUCTURAL_SURFACE:
            assert (REPO_ROOT / rel).is_file(), f"{rel} moved without updating this census"


class TestRunBindingsProductionAdoption:
    def test_the_carrier_has_a_production_construction_site_at_all(self):
        """The bluntest form of the finding: grep production for a writer.

        Kept beside the structural test because it is the one that would have
        caught the real defect on day one — the class existed, the guard
        existed, the tests existed, and `grep -r 'WorkflowRunBindings(' --
        excluding tests` returned nothing.
        """
        sites = []
        sources = [*REPO_ROOT.glob("*.py")]
        for root in ("src", "scripts"):
            files = list((REPO_ROOT / root).rglob("*.py"))
            assert files, f"empty production scan: {root}"
            sources.extend(files)
        for path in sources:
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel.startswith(("tests/", ".venv/", "docs/")):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "WorkflowRunBindings"
                ):
                    sites.append(rel)
        assert sites, "no production module constructs WorkflowRunBindings"
        # Independent native entrypoints each construct their own run authority.
        # Counting actual calls rejects missing, duplicate and comment-only writers.
        assert sorted(sites) == [
            "src/tools/candidate_worker/training_admission.py",
            "src/workflows/model_exploration.py",
        ], sites
