"""Step 09.5a C0 — the executable censuses.

Three source facts the migration must not silently break, each pinned here
BEFORE any production edit so the baseline is recorded rather than reconstructed.

Defects only these catch:

* **census A** — a ``run_workflow`` parameter exists that no ownership class
  claims. The design's field table (§5) is prose; without this check the table
  can drift from the signature the moment either side moves, and a value with no
  owner is exactly how a parameter bag reforms.
* **census D** — a production caller was not migrated. ``pyright`` catches a
  wrong keyword, but not a caller nobody remembered to look at.
* **census B** — a second committed-digest read/parse authority exists. This is
  the A-2 regression, and it is invisible to behaviour: four readers and one
  reader produce identical results.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

# ---------------------------------------------------------------------------
# Census A — every run_workflow parameter has exactly one ownership class
# ---------------------------------------------------------------------------

#: The frozen design's classification (§5), transcribed once. A parameter that
#: is not in exactly one of these sets fails the census — which is the point:
#: the design table and the live signature must not be able to drift apart.
CLASS_A_AUTHORITIES = frozenset(
    {
        "workspace",
        "run_name",
        "chain_run_name",
        "run_id",
        "data_scope",
        "health_gate_enabled",
        "health_gate_files",
        "health_checks_config",
        "order_strategy_override",
        "file_order_override",
        "enable_structured_health_feedback",
        "llm_config",
        # Step 10 / P1 C5: the run's TASK composition — the most literal
        # class-A value there is (an authority settled once, at the
        # composition edge, whose identity does not change for the run).
        "task_composition",
    }
)

#: Step 10 / P1 C5 closes 09.5a's own C4b hand-off: the NINE restored seeds
#: are ONE typed parameter. The class does not disappear — the values still
#: seed `ChainState` and are still class B — it is the TRANSPORT that
#: collapsed. `RestoredState` is resume's own type and is allowed across the
#: launcher edge (09.5a §16); `ChainState` still never crosses one.
CLASS_B_CHAIN_STATE_SEEDS = frozenset({"restored_state"})

#: The nine kwargs this replaced, kept so the census can prove they are GONE
#: rather than merely absent from the class table. Re-adding any one of them
#: is the first step back toward a signature that grows with every value
#: resume learns to carry.
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

#: Amendment A: immutable capability references only. `require_probe_runner` is
#: deliberately NOT here — the per-field audit found it is a plain bool launch
#: flag, and keeping it here would have been the "compress the signature"
#: reasoning the amendment forbids.
CLASS_D_CAPABILITIES = frozenset({"bridge_factory", "sandbox_factory", "measurement_capability"})

#: DS7 no-ops (`workflows/model_exploration.py:1718-1732`). Kept for behaviour
#: parity; they enter no carrier.
CLASS_F_DEPRECATED_NOOPS = frozenset({"trial_strategy", "target_files", "eval_strategy"})

_EXPLICIT = (
    CLASS_A_AUTHORITIES
    | CLASS_B_CHAIN_STATE_SEEDS
    | CLASS_D_CAPABILITIES
    | CLASS_F_DEPRECATED_NOOPS
)


def _run_workflow_parameters() -> list[str]:
    from workflows.model_exploration import run_workflow

    return list(inspect.signature(run_workflow).parameters)


class TestParameterOwnershipCensus:
    def test_every_parameter_has_exactly_one_ownership_class(self):
        """Class C is the complement, so this asserts the partition is total."""
        params = _run_workflow_parameters()
        overlaps = {
            p
            for p in params
            if sum(
                p in s
                for s in (
                    CLASS_A_AUTHORITIES,
                    CLASS_B_CHAIN_STATE_SEEDS,
                    CLASS_D_CAPABILITIES,
                    CLASS_F_DEPRECATED_NOOPS,
                )
            )
            > 1
        }
        assert not overlaps, f"parameters claimed by two ownership classes: {sorted(overlaps)}"

        stale = sorted(_EXPLICIT - set(params))
        assert not stale, (
            "the design's field table names parameters that no longer exist on "
            f"run_workflow: {stale}. Update §5 and this census together."
        )

    def test_the_class_totals_reconcile_to_the_live_signature(self):
        """A + B + C + D + F == len(signature), with C the complement.

        MEASURED at the design anchor: 12 + 9 + 72 + 3 + 3 = 99.
        After 09.5a C3 the 72 transit values became one `launch` carrier;
        after Step 10 / P1 C5 the 9 restored seeds became one `restored_state`
        and one `task_composition` authority joined class A: 13 + 1 + 1 + 3 +
        3 = 21.
        """
        params = _run_workflow_parameters()
        class_c = [p for p in params if p not in _EXPLICIT]
        total = (
            len(CLASS_A_AUTHORITIES)
            + len(CLASS_B_CHAIN_STATE_SEEDS)
            + len(class_c)
            + len(CLASS_D_CAPABILITIES)
            + len(CLASS_F_DEPRECATED_NOOPS)
        )
        assert total == len(params), (
            f"ownership classes sum to {total} but run_workflow has {len(params)} parameters"
        )

    def test_the_census_is_not_vacuous(self):
        """A signature that lost its parameters would satisfy a partition check.

        The floor was 50 before C3 and is re-derived here from the migrated
        shape, exactly as the pre-C3 message instructed: after the migration
        the signature carries the 12 authorities, 9 restored seeds, 3
        capability references, 3 DS7 no-ops and `launch` — 28. Deleting the
        guard instead of re-deriving it is how a partition check becomes
        decoration.

        RE-DERIVED at Step 10 / P1 C5, following that instruction rather than
        deleting the guard: 13 class-A authorities (the original 12 plus
        `task_composition`), 1 restored-state carrier, 3 capability
        references, 3 DS7 no-ops and `launch` — **21**, the count the P1
        design freezes.
        """
        params = _run_workflow_parameters()
        assert len(params) == 21, (
            f"run_workflow has {len(params)} parameters, not the 21 the Step-10 "
            "P1 design freezes. If a later migration legitimately changes it, "
            "re-derive this count from the new signature rather than deleting "
            "the guard."
        )
        assert CLASS_A_AUTHORITIES and CLASS_B_CHAIN_STATE_SEEDS and CLASS_D_CAPABILITIES

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


# ---------------------------------------------------------------------------
# Census D — production callers of run_workflow
# ---------------------------------------------------------------------------

#: MEASURED at the design anchor. Every one must migrate atomically in C3.
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


# ---------------------------------------------------------------------------
# Census B — committed-digest read/parse authorities
# ---------------------------------------------------------------------------


#: Production modules that may legitimately mention the digest path convention.
#: Anything else resolving it is a second reader.
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


#: MEASURED at the design anchor, then REDUCED by C1. The A-2 finding was four
#: duplicated read/parse/soft-fail implementations; after C1 there is exactly
#: ONE, and the four carried values became pure projections over its output.
DIGEST_IO_AUTHORITIES = frozenset({"src/core/committed_digests.py::read_committed_digests"})

#: The four projections that consume the authority's output. They must remain
#: distinct — their validators, merge rules and failure policies genuinely
#: differ (two raise, one warns-and-drops, one ignores a non-dict).
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
