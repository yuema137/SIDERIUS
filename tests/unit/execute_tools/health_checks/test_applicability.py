"""Step 08a C2 — check input declarations and the pure applicability engine.

Design authority: ``docs/design/generic_framework_upgrade/
step_08_health_check_task_profile/pr_08a_check_input_contract.md`` §3.2-§3.3,
§4.2.

Defect classes owned here, none of which a static checker or Pydantic can
reach:

* an inapplicability that stops NAMING which axis decided it — the reason a
  persisted "not applicable" is auditable at all;
* an ABSENT axis being reported as a MISMATCHED one (or vice versa): "this
  task declares nothing about encoding" and "this task declares a different
  encoding" are different situations with different fixes;
* the evaluation ORDER silently flipping, so an expensive/derived question
  is asked before a free one;
* a declaration authored with a typo'd axis or context input becoming
  permanently, silently inapplicable instead of failing at authoring time;
* the regime-A derivation drifting away from what the profile actually says.

The engine is deliberately UNREACHABLE from production in C2 — a test in
this module asserts that, and C3 removes it when the wiring lands.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from execute_tools.dataset_config import resolve_dataset_profile
from execute_tools.health_checks._regime_a_facts import derive_health_facts, resolve_health_facts
from execute_tools.health_checks.schemas import (
    APPLICABLE,
    CheckInputDeclaration,
    FactRequirement,
    HealthCheckContext,
    TaskHealthFacts,
    applicability,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
"""tests/unit/execute_tools/health_checks/<this file> → four hops to the root.

Derived from this file's location so the test reads the checkout it is being
executed from (CLAUDE.md portability rule) — and asserted below, because an
off-by-one here would run ``git grep`` outside the repository and let the
guard pass vacuously."""

PRODUCTION_PACKAGES = ("execute_tools", "nodes", "agent", "core", "scripts")


def _ctx(**overrides) -> HealthCheckContext:
    base = {"model_name": "m", "run_name": "r", "round_index": 1}
    base.update(overrides)
    return HealthCheckContext(**base)


def _full_ctx() -> HealthCheckContext:
    """A context in which every declarable input is present."""
    return _ctx(
        denoised_paths={0: "/tmp/denoised_0000.h5"},
        target_path_fn=lambda fi: f"/tmp/target_{fi:04d}.h5",
        file_vector=[1.0, 2.0],
        denoising_score=3.0,
    )


# The facts TIDMAD's profile implies, and a contrast task's declaration.
TIDMAD_FACTS = TaskHealthFacts(
    encoding_family="int8_symbol_stream",
    symbol_cardinality=256,
    file_group_size=20,
    sampling_frequency_hz=10_000_000.0,
)
CONTRAST_FACTS = TaskHealthFacts(
    encoding_family="continuous_float",
    value_scale_unit="mV",
    file_group_size=4,
)

# Stand-ins for the six shipped checks' declarations. C4 replaces these with
# the real ClassVars; here they only have to be SHAPED like them.
INT8_PEEK_DECLARATION = CheckInputDeclaration(
    consumes_view="tidmad.int8_prefix_peek",
    required_context_inputs=("denoised_source",),
    required_facts=(FactRequirement(axis="encoding_family", equals="int8_symbol_stream"),),
    threshold_parameter_names=("min_unique_int8_values",),
)
TARGET_COMPARISON_DECLARATION = CheckInputDeclaration(
    consumes_view="tidmad.target_comparison_peek",
    required_context_inputs=("denoised_source", "target_source"),
    required_facts=(FactRequirement(axis="encoding_family", equals="int8_symbol_stream"),),
)


class TestApplicableUnderTidmadFacts:
    """Every TIDMAD-shaped declaration applies under TIDMAD facts.

    This is the parity claim in its pure form: if any of these flipped, the
    wiring commit would silently stop running a production check.
    """

    @pytest.mark.parametrize(
        "declaration",
        [INT8_PEEK_DECLARATION, TARGET_COMPARISON_DECLARATION],
        ids=["int8_peek", "target_comparison"],
    )
    def test_declaration_is_applicable(self, declaration: CheckInputDeclaration):
        verdict = applicability(declaration, TIDMAD_FACTS, _full_ctx())
        assert verdict.applicable is True
        assert verdict.axis is None
        assert verdict.reason == ""

    def test_empty_declaration_is_applicable_anywhere(self):
        """Declaring no requirements is a claim ("I run anywhere"), not a gap."""
        verdict = applicability(
            CheckInputDeclaration(consumes_view="anything"), CONTRAST_FACTS, _ctx()
        )
        assert verdict is APPLICABLE


class TestFactAxisMismatch:
    def test_contrast_facts_make_the_int8_family_inapplicable(self):
        """8.4-B in its pure form: declared-float task ⇒ int8 checks do not apply."""
        verdict = applicability(INT8_PEEK_DECLARATION, CONTRAST_FACTS, _full_ctx())
        assert verdict.applicable is False
        assert verdict.axis == "encoding_family"
        assert verdict.reason == (
            "not applicable — encoding_family is 'continuous_float', "
            "check requires 'int8_symbol_stream'"
        )

    def test_absent_axis_is_reported_as_absent_not_as_mismatched(self):
        """The distinction that a boolean 'satisfied?' would destroy."""
        silent = TaskHealthFacts(file_group_size=4)
        verdict = applicability(INT8_PEEK_DECLARATION, silent, _full_ctx())
        assert verdict.applicable is False
        assert verdict.axis == "encoding_family"
        assert verdict.reason == "not applicable — task declares no 'encoding_family' fact"
        assert "requires" not in verdict.reason

    def test_presence_only_requirement_is_satisfied_by_any_value(self):
        declaration = CheckInputDeclaration(
            consumes_view="v", required_facts=(FactRequirement(axis="value_scale_unit"),)
        )
        assert applicability(declaration, CONTRAST_FACTS, _ctx()).applicable is True
        verdict = applicability(declaration, TIDMAD_FACTS, _ctx())
        assert verdict.applicable is False
        assert verdict.axis == "value_scale_unit"


class TestContextInputPresence:
    def test_absent_target_source_names_the_missing_input(self):
        """Today's ``pearson_dispersion`` NA case, decided before the check runs."""
        ctx = _ctx(denoised_paths={0: "/tmp/d.h5"})  # no target_path_fn
        verdict = applicability(TARGET_COMPARISON_DECLARATION, TIDMAD_FACTS, ctx)
        assert verdict.applicable is False
        assert verdict.axis == "target_source"
        assert verdict.reason == "not applicable — required context input 'target_source' is absent"

    def test_denoised_source_is_satisfied_by_either_carrier(self):
        """The disjunction is why the vocabulary is logical, not raw field names."""
        declaration = CheckInputDeclaration(
            consumes_view="v", required_context_inputs=("denoised_source",)
        )
        by_paths = _ctx(denoised_paths={0: "/tmp/d.h5"})
        by_callable = _ctx(denoised_filename_fn=lambda fi: "/tmp/d.h5")
        assert applicability(declaration, TIDMAD_FACTS, by_paths).applicable is True
        assert applicability(declaration, TIDMAD_FACTS, by_callable).applicable is True
        assert applicability(declaration, TIDMAD_FACTS, _ctx()).applicable is False

    def test_empty_collections_count_as_absent(self):
        """An empty file_vector is no evidence, not evidence of emptiness."""
        declaration = CheckInputDeclaration(
            consumes_view="v", required_context_inputs=("file_vector",)
        )
        assert applicability(declaration, TIDMAD_FACTS, _ctx(file_vector=[])).applicable is False
        assert applicability(declaration, TIDMAD_FACTS, _ctx(file_vector=[1.0])).applicable is True


class TestEvaluationOrder:
    def test_context_inputs_are_decided_before_fact_axes(self):
        """Cheapest question first — and the reason must be deterministic.

        This test fails if the order flips: with BOTH a missing context input
        and a mismatched fact axis, the context input must win.
        """
        declaration = CheckInputDeclaration(
            consumes_view="v",
            required_context_inputs=("target_source",),
            required_facts=(FactRequirement(axis="encoding_family", equals="int8_symbol_stream"),),
        )
        verdict = applicability(declaration, CONTRAST_FACTS, _ctx())
        assert verdict.axis == "target_source"

    def test_first_declared_requirement_wins_within_a_kind(self):
        declaration = CheckInputDeclaration(
            consumes_view="v",
            required_context_inputs=("file_vector", "target_source"),
        )
        assert applicability(declaration, TIDMAD_FACTS, _ctx()).axis == "file_vector"

    def test_reason_strings_are_deterministic(self):
        """Reasons are persisted evidence; identical inputs must give identical bytes."""
        first = applicability(INT8_PEEK_DECLARATION, CONTRAST_FACTS, _full_ctx())
        second = applicability(INT8_PEEK_DECLARATION, CONTRAST_FACTS, _full_ctx())
        assert first.reason == second.reason
        assert first == second


class TestAuthoringTimeFailClosed:
    def test_unknown_fact_axis_rejected(self):
        with pytest.raises(ValidationError, match="Unknown health fact axis"):
            FactRequirement(axis="encodng_family", equals="int8_symbol_stream")

    def test_unknown_context_input_rejected(self):
        with pytest.raises(ValidationError, match="Unknown context input"):
            CheckInputDeclaration(consumes_view="v", required_context_inputs=("denoised_pathz",))

    def test_symbol_cardinality_without_a_family_is_rejected(self):
        with pytest.raises(ValidationError, match="without encoding_family"):
            TaskHealthFacts(symbol_cardinality=256)

    def test_degenerate_symbol_cardinality_is_rejected(self):
        with pytest.raises(ValidationError):
            TaskHealthFacts(encoding_family="f", symbol_cardinality=1)

    def test_inapplicable_verdict_must_name_an_axis(self):
        """Enforced on the type, so no producer can emit an unattributed refusal."""
        from execute_tools.health_checks.schemas import ApplicabilityVerdict

        with pytest.raises(ValidationError, match="must name the deciding axis"):
            ApplicabilityVerdict(applicable=False, reason="nope")
        with pytest.raises(ValidationError, match="carries no axis and no reason"):
            ApplicabilityVerdict(applicable=True, axis="encoding_family", reason="x")


class TestRegimeADerivation:
    """The derived facts are pinned to HARDCODED values, never read back."""

    def test_tidmad_profile_derives_the_expected_facts(self):
        facts = derive_health_facts(resolve_dataset_profile())
        assert facts.encoding_family == "int8_symbol_stream"
        assert facts.symbol_cardinality == 256
        assert facts.file_group_size == 20
        assert facts.sampling_frequency_hz == 10_000_000.0

    def test_value_scale_unit_is_deliberately_absent(self):
        """The mV scale is a check-local literal, not a task declaration.

        Deriving it would invent a declaration the task never made; REQUIRING
        it would flip TIDMAD's std checks to inapplicable. Ownership moves
        with the thresholds in 08b.
        """
        assert derive_health_facts(resolve_dataset_profile()).value_scale_unit is None

    def test_resolved_facts_match_the_explicit_derivation(self):
        assert resolve_health_facts() == derive_health_facts(resolve_dataset_profile())

    def test_derived_tidmad_facts_satisfy_the_int8_family_declaration(self):
        """Ties the derivation to the parity claim rather than to a literal."""
        verdict = applicability(
            INT8_PEEK_DECLARATION, derive_health_facts(resolve_dataset_profile()), _full_ctx()
        )
        assert verdict.applicable is True


class TestEngineIsWiredExactlyOnce:
    """C2 asserted the engine was UNREACHABLE; C3 wired it.

    The guard is not deleted, it is INVERTED: production must call the
    applicability engine from exactly one place. A second call site would
    mean two policies deciding what "does not apply" means, which is the
    duplication this whole seam exists to prevent — and it would be
    invisible to every behavioural test, because both sites would agree
    right up until one of them changed.
    """

    ONE_CALL_SITE = "execute_tools/health_checks/runner.py"

    @staticmethod
    def _git_grep(pattern: str) -> list[str]:
        proc = subprocess.run(
            # --untracked: a brand-new production module is exactly the case
            # this guard must catch, and git grep skips untracked files by
            # default.
            ["git", "grep", "-nE", "--untracked", pattern, "--", *PRODUCTION_PACKAGES],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        # 0 = matches, 1 = no matches. Anything else means the search did not
        # run, which must not be read as "no callers".
        assert proc.returncode in (0, 1), (
            f"git grep failed (rc={proc.returncode}) in {REPO_ROOT}: {proc.stderr.strip()}"
        )
        return proc.stdout.splitlines()

    def test_repo_root_resolves_to_this_checkout(self):
        """Guards the guard: a wrong root would make every grep below vacuous."""
        assert (REPO_ROOT / ".git").exists()
        assert (REPO_ROOT / "execute_tools" / "health_checks" / "schemas.py").is_file()

    def test_the_grep_probe_actually_finds_things(self):
        """Proves the search works, so its results below are real evidence."""
        definition = self._git_grep(r"(^|[^_A-Za-z0-9])applicability\(")
        assert any("def applicability(" in line for line in definition), definition

    def test_exactly_one_production_call_site(self):
        # The identifier-boundary class matters: ``classify_applicability(``
        # in core/runtime_control is an unrelated function, and matching it
        # would make this guard cry wolf until someone deleted it.
        callers = [
            line
            for line in self._git_grep(r"(^|[^_A-Za-z0-9])applicability\(")
            if "def applicability(" not in line
        ]
        assert len(callers) == 1, "expected exactly one call site, got:\n" + "\n".join(callers)
        assert callers[0].startswith(self.ONE_CALL_SITE), callers[0]

    def test_the_call_site_is_the_gate_runner(self):
        """Applicability must be decided by the RUNNER, before it invokes a skill.

        If the decision migrated into the checks, each check would again be
        answering "do I apply?" after it had already been handed control —
        which is where the pre-08a NA-as-pass convention came from.
        """
        importers = [
            line
            for line in self._git_grep(r"^[^:]*:[0-9]+:.*\bapplicability\b")
            if "health_checks/schemas.py" not in line
        ]
        offenders = [line for line in importers if not line.startswith(self.ONE_CALL_SITE)]
        assert not offenders, "applicability referenced outside the runner:\n" + "\n".join(
            offenders
        )
