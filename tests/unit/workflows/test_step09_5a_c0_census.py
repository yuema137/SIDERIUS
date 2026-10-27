"""Workflow carrier boundaries, production callers and committed-digest I/O ownership."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


RETIRED_RESTORED_KWARGS = frozenset(
    {
        "restored_runtime_vocab",
        "accumulated_key_findings",
        "restored_model_knowledge_cache",
        "accumulated_physical_rejections",
        "accumulated_gate_exhaustions",
        "restored_previous_proposal",
        "restored_chain_incumbent_score",
        "restored_collapse_fingerprint_history",
        "restored_prediction_memory",
    }
)


def _run_workflow_parameters() -> list[str]:
    from workflows.model_exploration import run_workflow

    return list(inspect.signature(run_workflow).parameters)


class TestParameterOwnershipCensus:
    def test_the_nine_restored_kwargs_really_left_the_signature(self):
        """C5's whole point, stated the way C3's transit check is stated.

        Defect this catches: a restored value quietly re-added as its own
        parameter — the shape that grew by one every time resume learned to
        carry something new."""
        params = set(_run_workflow_parameters())
        leaked = sorted(RETIRED_RESTORED_KWARGS & params)
        assert not leaked, (
            f"restored chain state is back on the signature as individual "
            f"parameters: {leaked}. It belongs inside RestoredState."
        )

    def test_the_transit_configuration_left_the_signature(self):
        """C3's whole point: the 72 pass-through values are ONE carrier now.

        Defect this catches: a transit value quietly re-added as an individual
        parameter — the first step back to a 99-parameter signature.
        """
        from workflows.run_config import launch_config_field_names

        params = set(_run_workflow_parameters())
        assert "launch" in params, "the transit carrier is not on the signature"
        leaked = sorted(launch_config_field_names() & params)
        assert not leaked, (
            f"transit configuration is back on the signature as individual "
            f"parameters: {leaked}. It belongs to WorkflowLaunchConfig."
        )


EXPECTED_PRODUCTION_CALLERS = frozenset(
    {
        "src/workflows/run_one_iteration.py",
        "src/workflows/model_exploration.py",
    }
)


_PRODUCTION_DIRS = (
    "src/agent",
    "src/core",
    "src/nodes",
    "src/workflows",
    "scripts",
    "src/execute_tools",
    "scripts/launch",
    "src/tools",
    "src/dashboard",
    "src/ml_models",
)


def _production_call_sites() -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for d in _PRODUCTION_DIRS:
        root = REPO_ROOT / d
        if not root.is_dir():
            continue
        for py in sorted(root.rglob("*.py")):
            try:
                tree = ast.parse(py.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):  # pragma: no cover
                continue
            lines = [
                n.lineno
                for n in ast.walk(tree)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "run_workflow"
            ]
            if lines:
                out[str(py.relative_to(REPO_ROOT))] = lines
    return out


class TestCallerCensus:
    def test_the_production_caller_set_is_exactly_the_frozen_set(self):
        found = set(_production_call_sites())
        assert found == set(EXPECTED_PRODUCTION_CALLERS), (
            "run_workflow's production callers changed. Every caller must migrate "
            "atomically to the typed boundary (design §13) — update this census in "
            f"the same commit.\n  added:   {sorted(found - EXPECTED_PRODUCTION_CALLERS)}"
            f"\n  removed: {sorted(EXPECTED_PRODUCTION_CALLERS - found)}"
        )

    def test_the_caller_census_is_not_vacuous(self):
        sites = _production_call_sites()
        assert len(sites) >= 2, f"expected >= 2 production call sites, found {sites}"


_DIGEST_PATH_OWNERS = ("src/core/committed_digests.py", "src/core/resume.py")


def _digest_openers() -> dict[str, list[str]]:
    """Every production function that OPENS a file it resolved from the
    interpretation-digest path convention.

    Opening is the marker that matters for A-2: a projection may name the path
    convention, but only an authority may open it.
    """
    out: dict[str, list[str]] = {}
    for rel in _DIGEST_PATH_OWNERS:
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            opens = [
                c
                for c in ast.walk(fn)
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "open"
            ]
            resolves = [
                c
                for c in ast.walk(fn)
                if isinstance(c, ast.Call)
                and isinstance(c.func, ast.Name)
                and c.func.id in {"interpretation_digest_path", "_interpretation_path"}
            ]
            if opens and resolves:
                out[f"{rel}::{fn.name}"] = [ast.unparse(c.func) for c in opens]
    return out


DIGEST_IO_AUTHORITIES = frozenset({"src/core/committed_digests.py::read_committed_digests"})


PROJECTIONS = frozenset(
    {
        "project_knowledge",
        "project_knowledge_cache",
        "project_fingerprint_history",
        "project_prediction_memory",
    }
)


class TestCommittedDigestAuthorityCensus:
    def test_there_is_exactly_one_digest_io_authority(self):
        """A-2 solved, and provably so.

        Defect only this catches: a fifth carried value added later that brings
        its own `open()` back — behaviour would be identical, which is exactly
        why no behavioural test would notice.
        """
        openers = _digest_openers()
        assert set(openers) == set(DIGEST_IO_AUTHORITIES), (
            "the committed-digest I/O authority set moved. Exactly ONE function "
            "may open a digest it resolved (design §14, Amendment D).\n"
            f"  found: {sorted(openers)}"
        )

    def test_the_projections_do_no_io_of_their_own(self):
        """Amendment D: a projection may re-emit a diagnostic, never reopen."""
        from core import resume

        src = (REPO_ROOT / "src/core" / "resume.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            if fn.name not in PROJECTIONS:
                continue
            opens = [
                c
                for c in ast.walk(fn)
                if isinstance(c, ast.Call)
                and isinstance(c.func, ast.Name)
                and c.func.id in {"open", "json"}
            ]
            assert not opens, f"{fn.name} performs its own I/O — Amendment D forbids it"
            assert hasattr(resume, fn.name)

    def test_all_four_projections_survive_as_distinct_functions(self):
        """They must not be collapsed into one 'generic' loader: their
        malformed-value policies differ (raise / warn-and-drop / ignore)."""
        from core import resume

        missing = sorted(p for p in PROJECTIONS if not hasattr(resume, p))
        assert not missing, f"projection(s) lost: {missing}"

    def test_load_latest_proposal_is_not_routed_through_the_authority(self):
        """It reads a DIFFERENT file family and must never be folded in.

        `_proposal_path`, reverse iteration, first-parseable-wins (§3.4/§14.4).
        Name similarity is the trap; this pins that it stays separate.
        """
        assert "src/core/resume.py::load_latest_proposal" not in _digest_openers()
        src = (REPO_ROOT / "src/core" / "resume.py").read_text(encoding="utf-8")
        body = src[src.index("def load_latest_proposal") :]
        body = body[: body.index("\ndef ")]
        assert "read_committed_digests" not in body
        assert "_proposal_path" in body
