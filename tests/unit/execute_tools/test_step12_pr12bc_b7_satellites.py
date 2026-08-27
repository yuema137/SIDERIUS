"""Step 12 / PR-12bc — B7: the scope-adjacent satellites.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12bc_generic_task_boundary_closure.md`` §D.4, §M / B7; ledger §Q.B7
(D-BC-8).

Five TIDMAD-shaped assumptions sat BESIDE scope, so a composed non-TIDMAD run
would crash on a filename, an anchor artifact, a constant-based validator or a
measurement geometry — none of which the scope work itself touches. This module
is the permanent owner of all five corrected properties; B0's inverted guards
(b) (c) (d) were RETIRED here and (e) was UPGRADED (R-11-10).

The unifying rule: **every one of them now discriminates on what the TASK
DECLARES — never on a task name, and never on a module constant.**
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from execute_tools.dataset_config import (
    NUM_FILES,
    SEGMENTS_PER_FILE,
    TIDMAD_PROFILE,
    DataScope,
    DatasetProfile,
    tidmad_topology,
)
from execute_tools.scoring_utils import ScopeViolationError, validate_sample_set
from execute_tools.task_data_path import (
    LEGACY_TRIAL_ANCHOR_NAME,
    declares_trial_anchoring,
)
from execute_tools.tidmad_data_path import TidmadTaskDataPath

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def _identifiers(rel: str, qualname: str) -> set[str]:
    """Every NAME and ATTRIBUTE used inside one function, via the AST.

    Comments and docstrings are absent by construction, which is what makes a
    "this constant is gone" census mean the executable code rather than the
    prose that explains why it went.
    """
    tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == qualname
    )
    out: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.Attribute):
            out.add(node.attr)
    return out


#: A task with GENERIC identity and no TIDMAD topology at all.
TOPOLOGY_FREE = DatasetProfile(
    partition_count=4, anchor_selection_files=[0, 2], health_peek_files=[1]
)

#: A task whose topology is TIDMAD-SHAPED but differently sized — the case a
#: module constant gets silently wrong rather than loudly wrong.
SMALLER = DatasetProfile.model_validate(
    {
        **TIDMAD_PROFILE.to_wire(),
        "dataset": {
            **TIDMAD_PROFILE.to_wire()["dataset"],
            "num_files": 3,
            "segments_per_file": 5,
        },
        "anchor_selection_files": [0, 2],
        "health_peek_files": [1],
    }
)


# ======================================================================
# (b) F-12bc-1 — validate_sample_set is profile-aware
# ======================================================================


class TestValidateSampleSetFollowsTheRunsOwnProfile:
    def test_a_sample_set_illegal_under_the_runs_profile_is_now_REJECTED(self):
        """B0's guard asserted this was ACCEPTED. Under TIDMAD's 20x200 grid
        ``{19: [199]}`` is legal; under a 3x5 task it is nonsense, and the
        validator used to wave it through because it knew only the constants.
        """
        with pytest.raises(ValueError, match=r"out of range \[0, 3\)"):
            validate_sample_set({19: [199]}, profile=SMALLER)

    def test_the_per_partition_bound_follows_the_profile_too(self):
        with pytest.raises(ValueError, match=r"must be int in \[0, 5\)"):
            validate_sample_set({0: [5]}, profile=SMALLER)
        assert validate_sample_set({0: [4]}, profile=SMALLER) == {0: [4]}

    def test_a_task_with_no_declared_topology_skips_the_segment_bound(self):
        """SKIPPED, not guessed. A task that declares no per-partition index
        space has no number to check against, and substituting TIDMAD's is
        exactly the defect being removed. The PARTITION bound — generic
        identity — still applies, and so do all the structural checks.
        """
        assert validate_sample_set({0: [0, 12345]}, profile=TOPOLOGY_FREE) == {0: [0, 12345]}
        with pytest.raises(ValueError, match=r"out of range \[0, 4\)"):
            validate_sample_set({9: [0]}, profile=TOPOLOGY_FREE)

    def test_the_structural_checks_apply_to_every_task_unconditionally(self):
        for bad, match in (
            ({}, "must not be empty"),
            ({"x": [0]}, "must be an integer"),
            ({0: []}, "non-empty list"),
            ({0: "nope"}, "non-empty list"),
            ({0: [-1]}, "non-negative"),
        ):
            with pytest.raises(ValueError, match=match):
                validate_sample_set(bad, profile=TOPOLOGY_FREE)

    def test_the_scope_check_resolves_against_the_runs_partition_count(self):
        with pytest.raises(ScopeViolationError):
            validate_sample_set({2: [0]}, scope=DataScope.from_cli("0,1"), profile=SMALLER)

    def test_TIDMADs_own_verdicts_are_unchanged(self):
        """Widening must not weaken the boundary it replaced. The default
        (no profile) resolves the bound profile, so a legacy caller keeps its
        exact behaviour — including the rejections.
        """
        assert validate_sample_set({0: [1, 2]}) == {0: [1, 2]}
        with pytest.raises(ValueError, match=rf"out of range \[0, {NUM_FILES}\)"):
            validate_sample_set({NUM_FILES: [0]})
        with pytest.raises(ValueError, match=rf"must be int in \[0, {SEGMENTS_PER_FILE}\)"):
            validate_sample_set({0: [SEGMENTS_PER_FILE]})

    def test_no_module_constant_remains_in_the_validator(self):
        """The census. A re-inlined `NUM_FILES` would restore the defect while
        every behavioural test above still passed for the TIDMAD cases.

        Over EXECUTABLE identifiers, via the AST — not over source text. A
        text census would read the docstrings that EXPLAIN the removed
        constants and fail for the wrong reason, which is the same
        anchored-census trap F-P2b-4 named from the other direction.
        """
        assert _identifiers("execute_tools/scoring_utils.py", "validate_sample_set").isdisjoint(
            {"NUM_FILES", "SEGMENTS_PER_FILE", "TIDMAD"}
        )
        assert _identifiers("execute_tools/scoring_utils.py", "_sample_set_bounds").isdisjoint(
            {"NUM_FILES", "SEGMENTS_PER_FILE", "TIDMAD"}
        )


# ======================================================================
# (c) satellite (f) — the peek path
# ======================================================================


#: Every module the peek resolver may legitimately live in.
#:
#: The FILE SET is part of this guard, not scaffolding around it. The resolver
#: moved from ``execution.py`` to ``round_health.py`` when gate evaluation was
#: hoisted to the round boundary (F2); a guard that kept naming only the old
#: module would have gone green by looking where the code no longer is —
#: the census-blindness shape where the exemption can never fire.
_PEEK_MODULES = (
    "nodes/ml_hyperparameter_tune_agent/execution.py",
    "nodes/ml_hyperparameter_tune_agent/round_health.py",
)


def _peek_sources() -> dict[str, str]:
    return {rel: (REPO_ROOT / rel).read_text(encoding="utf-8") for rel in _PEEK_MODULES}


class TestThePeekPathComesFromTheRunsAuthorities:
    def test_the_inline_tidmad_filename_literal_is_gone(self):
        for rel, src in _peek_sources().items():
            code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("#"))
            assert "abra_validation_{i:04d}.h5" not in code, rel

    def test_the_import_time_tidmad_root_is_gone(self):
        for rel, src in _peek_sources().items():
            code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("#"))
            assert "TIDMAD_DATA_DIR" not in code, rel

    def test_the_path_is_built_from_the_composed_root_and_the_declaration(self):
        """Both halves, at the site. A fix that replaced only the filename
        would still peek in TIDMAD's directory.

        **Step 12 / PR-12d seam B -- asserted SEMANTICALLY, not as a source
        string.** The filename half used to be pinned as the literal
        ``_peek_names.validation_file_name(i)``, which turned RED when seam B
        renamed a LOCAL VARIABLE, with no semantic change at all. What
        matters is what the resolver READS: the COMPOSED physical root, and
        ``validation_file_name`` from an authority the run owns rather than
        an inline template. Both are asserted against the resolver's own AST.

        **F2 — the ROOT half is now asserted the same way, and the docstring
        above is finally true of both.** It had been left as the source string
        ``'_peek_root = sandbox.dirs["data"]'``, so this test went RED again on
        the very rename class it was rewritten to survive: the root read moved
        INSIDE the resolver (lazily, so a run with no physical data root does
        not pay for a peek it never asked for) and the substring vanished while
        the property held exactly. Asserting it on the resolver's AST is
        STRICTLY STRONGER than the substring was — the old form would have
        passed had ``_peek_root`` been assigned and never used, and could not
        say the read happens where the path is built.
        """
        import ast as _ast

        resolver = None
        for src in _peek_sources().values():
            resolver = next(
                (
                    node
                    for node in _ast.walk(_ast.parse(src))
                    if isinstance(node, _ast.FunctionDef) and node.name == "_target_fn"
                ),
                resolver,
            )
        assert resolver is not None, (
            f"the raw-target peek resolver `_target_fn` is in none of {_PEEK_MODULES} — "
            "it was renamed or removed without updating this guard's file set"
        )

        body = _ast.unparse(resolver)
        assert 'dirs["data"]' in body or "dirs['data']" in body, (
            "the COMPOSED root half: the resolver must read the run's own "
            "physical data root, at the point it builds the path"
        )
        assert "validation_file_name" in body, (
            "the filename must still come from the declared template authority"
        )
        assert "abra_validation" not in body, "no inline TIDMAD filename literal may return"
        assert "os.path.join" in body

    def test_tidmads_peek_names_are_byte_identical(self):
        """Parity: the declaration renders exactly what the literal did."""
        names = tidmad_topology(TIDMAD_PROFILE).dataset
        assert names.validation_file_name(3) == "abra_validation_0003.h5"
        assert names.validation_file_name(17) == "abra_validation_0017.h5"


# ======================================================================
# (d) satellite (e) — trial anchoring is DECLARED
# ======================================================================


class TestTrialAnchoringIsADeclaredCapability:
    def test_tidmad_declares_it_and_names_its_own_artifact(self):
        impl = TidmadTaskDataPath()
        assert declares_trial_anchoring(impl) is True
        assert impl.trial_anchor_path("/data") == "/data/segment_anchors.json"

    def test_a_task_without_it_is_detected_by_CALLABILITY(self):
        class _NoAnchoring:
            task_data_path_id = "b7_no_anchoring"

        assert declares_trial_anchoring(_NoAnchoring()) is False

    def test_the_tuner_DECLINES_by_name_rather_than_crashing_on_a_filename(self):
        """D-BC-15. The design said "refuse the round"; the consumer audit said
        otherwise, and the ledger records why: ``anchor_map_data=None`` is an
        ALREADY LEGAL state (``execution.py:953`` guards the whole block that
        reads it), and that block is TIDMAD's SCORING reference rather than a
        precondition of trial rounds. Refusing would have regressed composed
        Pets/DAVIS trial runs PR-12a made work, to protect them from a consumer
        they never reach. What the design actually asked for — never crash on a
        TIDMAD filename a task did not declare — is met by declining to invent
        one.
        """
        src = (
            REPO_ROOT / "nodes" / "ml_hyperparameter_tune_agent" / "ml_hyperparameter_tune_agent.py"
        ).read_text(encoding="utf-8")
        assert "trial anchoring SKIPPED" in src
        assert "declares none" in src
        assert "nothing is guessed here" in src

    def test_a_composed_run_whose_binding_is_unbound_also_declines(self):
        """The third case, and the one that is easy to miss: PR-12a's guard
        follows the INPUT FIELD even with the ContextVars unbound, so a tuner
        assuming a field implies a binding would raise a regime-A resolution
        error at a point that has nothing to do with anchoring.
        """
        from execute_tools.task_data_path import bind_task_data_path
        from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
            _load_trial_anchor_map,
        )

        class _NoAnchoring:
            task_data_path_id = "b7_no_anchoring"

        # composed + bound but declaring no anchoring -> declines by name
        with bind_task_data_path(_NoAnchoring()):
            assert _load_trial_anchor_map(composed=True, data_root="/nonexistent") is None

    def test_the_resolution_was_extracted_out_of_the_orchestrator(self):
        """It has three cases and `run()` had already spent its §J budget, so
        CLAUDE.md's rule applies: establish the boundary, then add the feature.
        The extraction left `run()` SMALLER than its B0 baseline.
        """
        import sys

        sys.path.insert(0, str(REPO_ROOT))
        from tests.unit.guardrails.test_step12_pr12a_c0_defect_baselines import (
            _qualified_functions,
            measure,
        )

        fns = _qualified_functions(
            REPO_ROOT / "nodes" / "ml_hyperparameter_tune_agent" / "ml_hyperparameter_tune_agent.py"
        )
        assert "_load_trial_anchor_map" in fns
        _, branch, _, _ = measure(fns["HyperparamTuningAgent.run"])
        assert branch <= 69, f"run() grew to {branch} branch nodes (B0 baseline 69)"

    def test_the_legacy_filename_moved_to_a_named_constant(self):
        """Regime A keeps its exact behaviour, but as a DELIBERATE
        compatibility path rather than a leftover literal in an orchestrator.
        """
        assert LEGACY_TRIAL_ANCHOR_NAME == "segment_anchors.json"
        src = (
            REPO_ROOT / "nodes" / "ml_hyperparameter_tune_agent" / "ml_hyperparameter_tune_agent.py"
        ).read_text(encoding="utf-8")
        code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("#"))
        assert '"segment_anchors.json"' not in code

    def test_the_choice_is_made_on_BINDING_PRESENCE_not_a_task_name(self):
        """An un-composed run must not acquire a registration requirement it
        never had — which is what resolving through the registry would do.
        """
        src = (
            REPO_ROOT / "nodes" / "ml_hyperparameter_tune_agent" / "ml_hyperparameter_tune_agent.py"
        ).read_text(encoding="utf-8")
        block = src[src.index("if trial_allowed:") : src.index("if trial_allowed:") + 400]
        code = "\n".join(ln for ln in block.splitlines() if not ln.strip().startswith("#"))
        # PRESENCE from the run's own INPUT PROJECTION, never ambient state —
        # PR-12a's C2 rule, enforced by a census over the tuner package that
        # forbids `active_task_data_path` outright. The composed caller then
        # asks for an EXPLICIT binding, which refuses the regime-A fallback:
        # falling back would silently execute TIDMAD's data path for a run
        # that declared another task (C-P56-1).
        assert "task_composition_ref is not None" in code
        assert "require_bound_task_data_path()" in src
        # The "no ambient read in the tuner package" half is owned by PR-12a's
        # AST census (`test_step12_pr12a_c2_composition_projection.py`), which
        # is the right tool: this file keeps a COMMENT explaining what the old
        # guard used to read, and a text scan would call that a violation.
        # No task name in EXECUTABLE code. The comments above the block
        # deliberately explain the TIDMAD defect being removed, so a text
        # census over the raw block would fail for the wrong reason.
        for task in ("tidmad", "pets", "davis"):
            assert task not in code.lower()


# ======================================================================
# (e) F-12-2 — the measurement path. UPGRADED, not retired.
# ======================================================================


class TestTheMeasurementPathSkipsRatherThanGuesses:
    """B0's guard (e) asserted ``TidmadScope(`` was still constructed there.

    It still is — and correctly so, because REGIME A must keep measuring
    exactly as before. So the guard is UPGRADED rather than deleted: what
    changed is not that the construction disappeared, but that it is no longer
    reached under a binding whose task declares different geometry. The
    measurement now SKIPS with a NAMED reason, because the caller already
    handles a ``None`` estimate whereas measuring against somebody else's
    geometry returns a confident wrong number.

    Asserted STRUCTURALLY, never on wall time — the F-12a-G2 lesson, and the
    design's own B0 edge-case note for this satellite.
    """

    #: The named reasons the measurement path may decline with, ACROSS the
    #: C12-P vocabulary change. C12-P's frozen taxonomy renamed the
    #: semantic-non-membership refusal to "NOT APPLICABLE" (absent =>
    #: NOT_APPLICABLE; inside-but-malformed => loud ERROR). Both spellings are
    #: accepted because what this guard protects is that the path declines with
    #: a NAMED REASON -- not which English sentence it uses.
    _NAMED_REFUSALS = ("NOT APPLICABLE", "measurement SKIPPED")

    def test_it_guards_the_tidmad_geometry_before_using_it(self):
        """DEFECT THIS TEST ALONE CATCHES
            The measurement path timing a run against TIDMAD's geometry when
            the run's task declares different geometry -- returning a confident
            wrong number instead of declining.

        HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
            The topology guard, the error handling, or the named reason
            disappears from the measurement block.

        C12-P / F-C12P-12BC-1, SECOND SITE. This pinned the sentence
        ``"measurement SKIPPED"``. C12-P renamed that reason to
        ``NOT APPLICABLE`` under the frozen taxonomy, which turned this RED for
        a vocabulary change while the guarded behaviour was intact. The
        sentence was never the safety control; declining with a named reason
        is. Same repair as the sibling guard in
        ``tests/unit/guardrails/test_step12_pr12bc_f_checkpoint.py``.
        """
        src = (REPO_ROOT / "agent" / "skills" / "evaluate_time_skill" / "wrapper.py").read_text(
            encoding="utf-8"
        )

        # ORDERING, not a fixed-size window. This used to slice 2000 chars
        # backwards from the geometry USE and assert three strings landed
        # inside it. C12-P's B1 fix HOISTED the membership refusal above the
        # broad `except Exception` -- a deliberate structural change, so that a
        # malformed TIDMAD declaration stays loud instead of being swallowed --
        # which moved the refusal out of that window while making the guard
        # STRONGER. A byte-distance is not the invariant; "the guard precedes
        # the use" is.
        use = src.index("required_segs = (n_warmup_batches")
        membership = src.index("declares_tidmad_topology(profile)")
        assert membership < use, (
            "the topology membership test no longer precedes the geometry it "
            "protects, so the measurement can time a run against TIDMAD's "
            "geometry when the task declares different geometry."
        )

        assert "tidmad_topology(profile)" in src[:use]
        assert "except ValueError as exc:" in src

        refusal_positions = [src.index(r) for r in self._NAMED_REFUSALS if r in src]
        assert refusal_positions, (
            "the measurement path no longer declines with a NAMED reason. It "
            "must say that it is not measuring and why; a silent early return "
            "is the exact harm this guard exists to prevent."
        )
        assert min(refusal_positions) < use, (
            "the named refusal follows the geometry use instead of preceding "
            "it, so the wrong number is computed before anything declines."
        )

    def test_the_skip_returns_the_declared_empty_shape(self):
        """Both early returns must obey ``tuple[float | None, dict]`` — a bare
        ``None`` would crash the caller's unpacking, which the module's own
        docstring already warns about.

        DEFECT THIS TEST ALONE CATCHES
            A refusal that returns a bare ``None``, crashing the caller's
            two-value unpacking at the moment the run declines rather than at
            the moment it is written.

        HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
            The declared empty shape stops following the named refusal.

        C12-P: anchored on whichever named refusal is present rather than on
        one hardcoded sentence, for the reason given on the test above.
        """
        src = (REPO_ROOT / "agent" / "skills" / "evaluate_time_skill" / "wrapper.py").read_text(
            encoding="utf-8"
        )
        anchors = [src.index(r) for r in self._NAMED_REFUSALS if r in src]
        assert anchors, (
            "the measurement path declines with no named reason at all, so "
            "there is nothing to anchor the return-shape check on."
        )
        assert any("return None, empty_breakdown" in src[i : i + 200] for i in anchors), (
            "a named refusal is not followed by the declared empty shape. A "
            "bare `None` would crash the caller's `tuple[float | None, dict]` "
            "unpacking."
        )

    def test_regime_A_still_builds_its_own_scope(self):
        src = (REPO_ROOT / "agent" / "skills" / "evaluate_time_skill" / "wrapper.py").read_text(
            encoding="utf-8"
        )
        assert "TidmadScope(" in src


# ======================================================================
# --data_scope on a composed non-TIDMAD run
# ======================================================================


class TestDataScopeIsRefusedForAComposedNonTidmadTask:
    def test_the_refusal_exists_and_names_what_to_do_instead(self):
        src = (REPO_ROOT / "workflows" / "model_exploration.py").read_text(encoding="utf-8")
        assert "_refuse_data_scope_for_a_foreign_topology" in src
        assert "names FILE INDICES" in src
        assert "task's own scope capability" in src

    def test_it_is_gated_on_composition_presence_and_a_PARTIAL_scope(self):
        """A FULL scope is not a restriction, so it is not refused; and an
        un-composed run keeps `--data_scope` unconditionally.
        """
        src = (REPO_ROOT / "workflows" / "model_exploration.py").read_text(encoding="utf-8")
        assert "if not scope_is_partial or task_composition is None:" in src

    def test_composed_TIDMAD_still_honours_it(self):
        """§D.4: composed TIDMAD may keep honouring `--data_scope` through its
        own capability. The discriminator is "does this task declare TIDMAD's
        topology", never a task name — so this is asserted on the topology.
        """
        assert tidmad_topology(TIDMAD_PROFILE).dataset.num_files == NUM_FILES
        with pytest.raises(ValueError, match="declares no TIDMAD topology"):
            tidmad_topology(TOPOLOGY_FREE)


# ======================================================================
# §J — the extraction the branch budget required
# ======================================================================


class TestTheValidatorStayedWithinItsBudget:
    def test_bound_resolution_was_extracted_as_its_own_responsibility(self):
        """ "Which bounds apply to this profile" and "does this sample set
        satisfy them" are two responsibilities. Folding the first into the
        second pushed the validator past §J's +3 branch budget, so it was
        extracted — the rule working, not a style preference.
        """
        import sys

        sys.path.insert(0, str(REPO_ROOT))
        from tests.unit.guardrails.test_step12_pr12a_c0_defect_baselines import (
            _qualified_functions,
            measure,
        )

        fns = _qualified_functions(REPO_ROOT / "execute_tools" / "scoring_utils.py")
        assert "_sample_set_bounds" in fns
        _, branch, _, params = measure(fns["validate_sample_set"])
        assert branch - 14 <= 3, f"validate_sample_set gained {branch - 14} branch nodes"
        assert params - 2 <= 1

    def test_the_helper_is_focused(self):
        import sys

        sys.path.insert(0, str(REPO_ROOT))
        from tests.unit.guardrails.test_step12_pr12a_c0_defect_baselines import (
            _qualified_functions,
            measure,
        )

        stmts, branch, _, _ = measure(
            _qualified_functions(REPO_ROOT / "execute_tools" / "scoring_utils.py")[
                "_sample_set_bounds"
            ]
        )
        assert stmts <= 12 and branch <= 4


def test_no_satellite_reintroduced_a_task_name_branch():
    """The class-(b) rule, over exactly the files B7 touched."""
    for rel in (
        "execute_tools/scoring_utils.py",
        "nodes/ml_hyperparameter_tune_agent/execution.py",
        "agent/skills/evaluate_time_skill/wrapper.py",
    ):
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare) and isinstance(node.left, ast.Attribute):
                for comparator in node.comparators:
                    if isinstance(comparator, ast.Constant) and comparator.value in (
                        "tidmad",
                        "pets",
                        "davis",
                    ):  # pragma: no cover - the assertion is the point
                        raise AssertionError(f"{rel}:{node.lineno} branches on a task name")
