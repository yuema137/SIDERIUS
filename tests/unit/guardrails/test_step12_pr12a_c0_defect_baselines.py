"""Step 12 / PR-12a — C0 INVERTED DEFECT GUARDS and the structural baseline.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12a_composed_path_closure.md`` §5 C0.

Every test in the ``TestInvertedGuard*`` classes asserts that a named defect
is PRESENT on today's source. That is deliberate: each later commit then FLIPS
a named guard instead of adding an unanchored new test, and a guard that was
never red cannot certify that the fix did anything.

===============  ==================================================  ==========
guard            defect asserted PRESENT                             flips in
===============  ==================================================  ==========
(a)              F-12-1 — the composed pre-flight resolves            C1
                 ``resolved_data_scope`` against the TIDMAD          RETIRED
                 constant, not the composed task's profile
(b-health)       the composed run's per-model Health roster is       C1
                 TIDMAD's                                            RETIRED
(b-tuner)        F-P56-3 — the tuner's own                            C2
                 ``build_run_invariants`` call passes NEITHER         RETIRED
                 identity kwarg
(c)              issue #234 — an unknown ``PLUGIN_OUTPUT_TYPE``       C4
                 silently loads as ``"classifier"``                  RETIRED
(d)              D16 — a ``log_loss`` metric identity is refused      C5
                 by a LEXICAL name check                             RETIRED
(e)              the composed run's planner prompt carries            C7
                 TIDMAD's science (five builtin model                 RETIRED
                 descriptions + the hardcoded metric literal)
===============  ==================================================  ==========

**R-11-10 applies**: when a guard's fix lands, the guard either becomes the
permanent owner of the corrected property or is deleted. No pre/post twins are
left behind. §8 of the design records each retirement.

THE STRUCTURAL BASELINE is NOT inverted. It records the C0 measurement of every
function PR-12a touches so C8 can perform the mandatory pre/post comparison. It
is a tripwire on GROWTH — a new branch family means "extract the responsibility
first" — and is silent on shrinkage, which is the direction the rule wants.
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "step10_p1"


@pytest.fixture(autouse=True)
def _isolated_run_scope():
    """Health check registration and the plugin run-scope are PROCESS-GLOBAL.

    Without this, a composed guard in this module leaves the previous task's
    plugins bound; the next attempt to load a DIFFERENT task family then
    cannot register, the roster silently degrades to the policy-only document
    with zero gates, and a later test renders a reflector prompt ~4 KB shorter
    than it should. That is exactly how the C0 legacy prompt-byte baseline
    started failing by test ORDER alone with no production change — the
    established isolation fixture from the P5+P6 wiring modules is the fix.
    """
    from execute_tools.health_checks import _plugin_binding
    from execute_tools.health_checks.registry import _PROVIDER_REGISTRY, _REGISTRY

    registry = dict(_REGISTRY)
    providers = dict(_PROVIDER_REGISTRY)
    _plugin_binding.reset_run_scope()
    try:
        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(registry)
        _PROVIDER_REGISTRY.clear()
        _PROVIDER_REGISTRY.update(providers)
        _plugin_binding.reset_run_scope()


# ======================================================================
# Structural baseline (NOT inverted; C8 compares against it)
# ======================================================================

_BRANCH_NODES = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.Try,
    ast.ExceptHandler,
    ast.With,
    ast.AsyncWith,
    ast.IfExp,
    ast.Assert,
    ast.BoolOp,
    ast.comprehension,
    ast.Match,
    ast.match_case,
)


def measure(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[int, int, int, int]:
    """``(stmts, branch, loc, params)`` for one function definition.

    Identical counting rules to the Step-11 C0 tripwire
    (``test_step11_c0_defect_baselines.measure``): statements include the
    ``def`` itself and exclude nested definitions; ``branch`` counts branching
    and context nodes; ``params`` counts every declared parameter including
    ``*args`` / ``**kwargs``.

    The parent §10 table was produced by a measurement that differs from this
    one by at most ±1 statement per function and +1 branch on ``run_workflow``
    (a counting-convention delta, recorded in the design's §8 ledger rather
    than silently absorbed). What a pre/post comparison needs is ONE tool used
    on both sides, so this module's own numbers — not the parent's — are the
    baseline C8 compares against.
    """
    stmts = 0
    branch = 0
    for node in ast.walk(fn):
        if node is not fn and isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            continue
        if isinstance(node, ast.stmt):
            stmts += 1
        if isinstance(node, _BRANCH_NODES):
            branch += 1
    args = fn.args
    params = (
        len(args.posonlyargs)
        + len(args.args)
        + len(args.kwonlyargs)
        + (1 if args.vararg else 0)
        + (1 if args.kwarg else 0)
    )
    assert fn.end_lineno is not None
    return stmts, branch, fn.end_lineno - fn.lineno + 1, params


def _qualified_functions(path: pathlib.Path) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, f"{prefix}{child.name}.")
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out[f"{prefix}{child.name}"] = child
                visit(child, f"{prefix}{child.name}.")

    visit(tree, "")
    return out


#: Frozen at the PR-12a implementation base ``eeb073dc`` (source ``e4cd5c18``).
#: ``"<repo-relative path>::<qualified name>" -> (stmts, branch, loc, params)``
#:
#: Line numbers are deliberately NOT frozen — the Step-11 C0 module learned
#: that pinning them turns every unrelated edit red, which is a tripwire firing
#: on the wrong signal.
STRUCTURAL_BASELINE: dict[str, tuple[int, int, int, int]] = {
    "workflows/model_exploration.py::run_workflow": (369, 144, 1567, 21),
    "workflows/model_exploration.py::_register_plugin": (60, 19, 175, 4),
    "workflows/model_exploration.py::should_run_literature_review": (4, 0, 29, 2),
    (
        "nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py"
        "::HyperparamTuningAgent.run"
    ): (258, 67, 1085, 2),
    # RE-RECORDED 2026-08-26 (Lane F / F14): 471 → landed master 551 (+80
    # accumulated, exactly at the growth ceiling) → +6 disclosure call →
    # 557; branch 32 → 31. Same ledger as the 12bc B0 twin row; the
    # decomposition-debt flag lives there.
    "nodes/ml_hyperparameter_tune_agent/planning.py::prepare_attempt": (117, 31, 557, 7),
    "nodes/ml_hyperparameter_tune_agent/execution.py::run_admission_preflight": (
        107,
        36,
        521,
        6,
    ),
    "nodes/ml_hyperparameter_tune_agent/execution.py::run_inference_scoring_health": (
        109,
        26,
        474,
        6,
    ),
    "sdsc_submission_scripts/run_one_iteration.py::compute_expected_invariants": (6, 3, 64, 2),
    "core/resume.py::restore_prior_state": (100, 47, 383, 4),
    "core/run_invariants.py::build_run_invariants": (8, 3, 103, 13),
    "core/run_invariants.py::validate_stamped_invariants": (25, 14, 101, 4),
    "ml_models/plugin_loader.py::_load_plugin": (23, 7, 46, 1),
    "ml_models/plugin_loader.py::register_model_in_memory": (16, 3, 48, 1),
    # RETIRED FROM THE TABLE by C5 (D16), in the commit that did it — the same
    # rule C0 wrote down for `_add_plugin_to_registries`:
    #
    #   `_is_loss_shaped`      (4, 1, 14, 1)  DELETED — the lexical rule itself
    #   `_reject_loss_shaped`  (6, 3, 14, 2)  became `_validate_metric_identifier`
    #                                         (5, 2, 41, 2)
    #
    # The successor is strictly SMALLER in responsibility — one check where
    # there were two, branch 3 -> 2, executable statements 4 -> 3 — and its LOC
    # grew only because it now documents what enforces the boundary instead.
    # Re-anchoring it here would make C8's comparison for this row vacuous, so
    # the numbers live in the design ledger (§8.7) where the reshaping is
    # explained, and the row leaves the growth budget it can no longer be
    # measured against.
}

#: Growth beyond these deltas means "extract the responsibility first"
#: (CLAUDE.md's responsibility-oriented decomposition rule; parent §10's
#: "sibling-shaped deltas only, any new branch family extracts first").
MAX_BRANCH_GROWTH = 3
MAX_LOC_GROWTH = 80
MAX_PARAM_GROWTH = 1


def current_structure() -> dict[str, tuple[int, int, int, int]]:
    """The live measurement, for C8's recorded pre/post comparison."""
    out: dict[str, tuple[int, int, int, int]] = {}
    by_file: dict[str, list[str]] = {}
    for key in STRUCTURAL_BASELINE:
        rel, name = key.split("::")
        by_file.setdefault(rel, []).append(name)
    for rel, names in by_file.items():
        fns = _qualified_functions(REPO_ROOT / rel)
        for name in names:
            if name in fns:
                out[f"{rel}::{name}"] = measure(fns[name])
    return out


class TestStructuralBudget:
    """PR-12a must not grow a touched function into a new responsibility."""

    def test_every_baselined_function_still_exists(self):
        """A budget over a renamed-away function would pass by measuring
        nothing. C6 retired ``_add_plugin_to_registries`` deliberately, and its
        row (13, 1, 44, 1) left this table in that same commit — the rule this
        docstring wrote down in advance, applied."""
        assert set(current_structure()) == set(STRUCTURAL_BASELINE)

    @pytest.mark.parametrize("key", sorted(STRUCTURAL_BASELINE))
    def test_no_function_grew_past_its_budget(self, key):
        _, branch, loc, params = current_structure()[key]
        _, base_branch, base_loc, base_params = STRUCTURAL_BASELINE[key]
        assert branch - base_branch <= MAX_BRANCH_GROWTH, (
            f"{key} gained {branch - base_branch} branch nodes "
            f"({base_branch} -> {branch}) — that is a new branch family. "
            f"Establish a typed boundary first (CLAUDE.md, parent §10)."
        )
        assert loc - base_loc <= MAX_LOC_GROWTH, (
            f"{key} grew {loc - base_loc} lines ({base_loc} -> {loc}). Extract before adding."
        )
        assert params - base_params <= MAX_PARAM_GROWTH, (
            f"{key} gained {params - base_params} parameters "
            f"({base_params} -> {params}); ``run_workflow`` was already at 21."
        )


# ======================================================================
# (a) F-12-1 and (b-health) — RETIRED, replaced by their permanent owners
# ======================================================================
#
# R-11-10: a guard whose fix has landed becomes the permanent owner of the
# corrected property or is DELETED. It is never kept beside its successor.
#
#   (a) F-12-1 composed pre-flight topology
#   (b-health) the composed run's Health family
#       -> both replaced in C1 by
#          tests/unit/workflows/test_step12_pr12a_c1_composed_invariants.py
#          (TestF121PreflightResolvesTheRunsTopology, TestW7ValueAgreement,
#           TestComposedHealthConfigHandoff)
#
# The tuner-level half of (b-health) — that the tuner's own
# `build_run_invariants` call passes NEITHER identity kwarg — is NOT closed by
# C1: C1 changes what the workflow HANDS the tuner, not what the tuner asks
# for. That half is C2's and lives with the fingerprint guard below.


# ======================================================================
# (b-tuner) — RETIRED, replaced by its permanent owner
# ======================================================================
#
# R-11-10 again. C2 landed the typed composition projection and BOTH of its
# consumers, so the guard that asserted the tuner asks for neither identity
# kwarg is replaced by
# tests/unit/workflows/test_step12_pr12a_c2_composition_projection.py
# (TestW4ReadsTheInputNotTheAmbientEnvironment,
#  TestThePerModelLockRecordsTheComposition,
#  TestTheStampsStillReadTheRunScopedAuthority).


# ======================================================================
# (c) issue #234 — RETIRED, replaced by its permanent owner
# ======================================================================
#
# R-11-10. C4 closed the fail-open and the 3-vs-2 vocabulary split, so the
# guard asserting an unknown PLUGIN_OUTPUT_TYPE loads as "classifier" is
# replaced by
# tests/unit/ml_models/test_step12_pr12a_c4_output_type_vocabulary.py
# (TestTheVocabularyIsOneAuthority, TestAnUnrecognisedDeclarationRefuses,
#  TestHybridStaysLoadBearingForBuiltins,
#  TestARequiredMalformedPluginFailsTheRunClosed).


# ======================================================================
# (d) D16 — RETIRED, replaced by its permanent owners
# ======================================================================
#
# R-11-10. C5 made `MetricSpec.id` opaque, so the guard asserting a `log_loss`
# identity is refused is replaced by the UPGRADED pins where the refusal used
# to live:
#   tests/unit/execute_tools/test_step06_c1_evaluation_metric.py
#     - ..._is_ACCEPTED_by_every_metric_type   (all three types agree)
#     - ..._malformed_identifier_is_still_refused_...  (the sibling check)
#     - test_loss_history_cannot_populate_a_metric_result_under_any_key
#       (the TYPED boundary, which is what was ever actually enforcing it)
#   tests/unit/examples/test_oxford_iiit_pet_pack.py
#     - test_log_loss_is_now_declarable_d16_closed  (the pack's own inverted
#       pin, which fired exactly as written)


# ======================================================================
# (e) composed prompt science — RETIRED, replaced by its permanent owner
# ======================================================================
#
# R-11-10, the last of the six. C7-2 gated seven blocks behind composition
# presence, so the guard asserting a composed planner prompt still renders
# TIDMAD's five built-in descriptions is replaced by
# tests/unit/workflows/test_step12_pr12a_c7_prompt_science.py
# (TestTheRenderersGateExactlyAsClassified,
#  TestAComposedRunsRenderedPromptsAreFreeOfTidmadScience,
#  TestTheAssemblySiteNeverLearnsAboutComposition).
#
# The legacy half stays where it was: the C0 legacy byte-parity module still
# owns the un-composed rendered manifest, and it did NOT move through any of
# this — only the template constants did, which is the disposition that
# module's own docstring wrote down in advance.
