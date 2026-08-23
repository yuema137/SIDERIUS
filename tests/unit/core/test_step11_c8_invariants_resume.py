"""Step 11 C8 — the last task token, and the ingress/lock asymmetry.

**F-11-5.** ``core/resume.py`` derived the full scope from
``list(range(TIDMAD.num_files))`` — the ONLY task token in a 1,772-line
file — while the sibling call site in ``model_exploration.py`` had already
been composition-aware for a milestone. A composed resume was comparing its
own records against TIDMAD's file count.

**F-11-6 / R-11-9.** ``_CANONICAL`` has included
``task_composition_fingerprint`` since Step 10, so the workspace LOCK
refuses a cross-composition resume. The INGRESS validator never looked at
it, so a record produced under a different composition could be restored
into a run that then compared it as its own. Closed under the frozen
three-case rule::

    legacy / un-composed run + unstamped record   -> READABLE
    composed run + record carrying a fingerprint  -> must MATCH
    composed run + UNSTAMPED legacy record        -> REFUSE

The third case is the one that needs saying out loud: "unstamped" means
*nothing was recorded*, not *nothing was composed*, so treating absence as
agreement is exactly how a foreign record slips in.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from core.run_invariants import (
    RunInvariants,
    RunInvariantsViolation,
    validate_stamped_invariants,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
RESUME = REPO_ROOT / "core" / "resume.py"

FULL_SCOPE = [0, 1, 2, 3]
FINGERPRINT_A = "a" * 64
FINGERPRINT_B = "b" * 64


def _invariants(**overrides) -> RunInvariants:
    base = {
        "resolved_data_scope": FULL_SCOPE,
        "health_gate_enabled": True,
        "health_config_sha256": "c" * 64,
        "runtime_estimator_identity": "est",
        "runtime_policy_identity": "pol",
    }
    base.update(overrides)
    return RunInvariants(**base)


def _stamped(**overrides) -> dict:
    base = {
        "resolved_data_scope": FULL_SCOPE,
        "health_gate_enabled": True,
        "health_config_sha256": "c" * 64,
    }
    base.update(overrides)
    return base


# ----------------------------------------------------------------------
# F-11-5 — zero task tokens in the resume path
# ----------------------------------------------------------------------


class TestResumeCarriesNoTaskToken:
    def test_no_task_identity_is_imported(self):
        tree = ast.parse(RESUME.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
        assert "TIDMAD" not in imported, (
            "core/resume.py imports a task identity again; the full scope "
            "must come from the run's own resolved profile"
        )

    def test_no_task_token_survives_in_code(self):
        """Prose may DISCUSS the removed token; code may not use it.

        Counted as a code string/name rather than a substring, so the
        explanatory comment recording what was removed does not trip it.
        """
        tree = ast.parse(RESUME.read_text(encoding="utf-8"))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        constants = {
            n.value
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
        }
        assert "TIDMAD" not in names | attrs
        assert not any("TIDMAD" in c for c in constants)

    def test_the_scope_comes_from_the_runs_own_profile(self):
        src = RESUME.read_text(encoding="utf-8")
        assert "resolve_dataset_profile().partition_count" in src

    def test_it_matches_the_sibling_call_site(self):
        """The sibling was already composition-aware; the two now derive the
        same way, which is the point of removing the divergence.
        """
        sibling = (REPO_ROOT / "workflows" / "model_exploration.py").read_text(encoding="utf-8")
        assert "_run_partitions = resolve_dataset_profile().partition_count" in sibling


# ----------------------------------------------------------------------
# R-11-9 — the three cases, each named
# ----------------------------------------------------------------------


class TestTheThreeCaseRule:
    def test_case_1_legacy_run_reads_an_unstamped_record(self):
        """An un-composed run is untouched — what keeps every pre-Step-10
        workspace readable.
        """
        validate_stamped_invariants(
            _stamped(),
            _invariants(task_composition_fingerprint=None),
            full_scope=FULL_SCOPE,
            source="legacy record",
        )

    def test_case_2_composed_run_accepts_a_matching_fingerprint(self):
        validate_stamped_invariants(
            _stamped(task_composition_fingerprint=FINGERPRINT_A),
            _invariants(task_composition_fingerprint=FINGERPRINT_A),
            full_scope=FULL_SCOPE,
            source="composed record",
        )

    def test_case_2_composed_run_refuses_a_different_fingerprint(self):
        with pytest.raises(RunInvariantsViolation, match="task_composition_fingerprint"):
            validate_stamped_invariants(
                _stamped(task_composition_fingerprint=FINGERPRINT_B),
                _invariants(task_composition_fingerprint=FINGERPRINT_A),
                full_scope=FULL_SCOPE,
                source="foreign record",
            )

    def test_case_3_composed_run_refuses_an_unstamped_legacy_record(self):
        """The named rule. A record written before composition existed
        cannot be certified as belonging to this composition.

        The `source` is deliberately NEUTRAL. A mutation exposed the reason:
        with `source="unstamped legacy record"` the assertion below passed
        even when the absence branch was disabled, because the validator
        echoes `source` into every message — the word was arriving from the
        test's own label rather than from the refusal's explanation.
        """
        with pytest.raises(RunInvariantsViolation) as exc:
            validate_stamped_invariants(
                _stamped(),
                _invariants(task_composition_fingerprint=FINGERPRINT_A),
                full_scope=FULL_SCOPE,
                source="record-under-test",
            )
        message = str(exc.value)
        assert "task_composition_fingerprint" in message
        assert "this run is COMPOSED" in message, (
            "an unstamped record under a composed run must be refused by the "
            "ABSENCE branch, which explains why absence is not agreement — "
            "not by falling through to a value-mismatch message"
        )
        assert "carries no fingerprint" in message

    def test_a_legacy_run_still_accepts_a_stamped_record(self):
        """Deliberately permissive: an un-composed run compares nothing,
        which is what case 1 says. The asymmetry is the point — a composed
        run has an identity to protect and a legacy one does not.
        """
        validate_stamped_invariants(
            _stamped(task_composition_fingerprint=FINGERPRINT_A),
            _invariants(task_composition_fingerprint=None),
            full_scope=FULL_SCOPE,
            source="stamped record, legacy run",
        )

    def test_the_other_three_stamps_still_behave(self):
        """C8 must not disturb the pre-existing legacy-aware rules."""
        with pytest.raises(RunInvariantsViolation, match="resolved_data_scope"):
            validate_stamped_invariants(
                _stamped(resolved_data_scope=[0, 1]),
                _invariants(),
                full_scope=FULL_SCOPE,
                source="scope mismatch",
            )


# ----------------------------------------------------------------------
# The stamp must actually be produced, or the rule refuses everything
# ----------------------------------------------------------------------


class TestTheStampIsProduced:
    """Without a producer the composed branch would refuse every record,
    including a composed run's own. This is the half that makes case 2
    reachable at all.
    """

    def test_the_record_schema_carries_it(self):
        from agent.schemas.hyperparam_tuning import ExperimentRecord

        field = ExperimentRecord.model_fields["task_composition_fingerprint"]
        assert field.default is None, "legacy records must still validate"

    def test_the_output_schema_carries_it(self):
        from agent.schemas.hyperparam_tuning import HyperparamTuningOutput

        field = HyperparamTuningOutput.model_fields["task_composition_fingerprint"]
        assert field.default is None

    def test_it_is_stamped_at_the_single_persist_seam(self):
        """One place, for the reason `candidate_id` is stamped there: nine
        construction sites, and a per-site stamp is one someone forgets.
        """
        src = (REPO_ROOT / "nodes/ml_hyperparameter_tune_agent/records.py").read_text(
            encoding="utf-8"
        )
        assert 'record["task_composition_fingerprint"] = active_composition_fingerprint()' in src

    def test_an_uncomposed_run_stamps_none(self):
        from workflows.task_composition import active_composition_fingerprint

        assert active_composition_fingerprint() is None

    def test_a_composed_run_binds_its_fingerprint(self):
        from workflows.task_composition import (
            active_composition_fingerprint,
            bind_composition_fingerprint,
        )

        with bind_composition_fingerprint(FINGERPRINT_A):
            assert active_composition_fingerprint() == FINGERPRINT_A
        assert active_composition_fingerprint() is None

    def test_the_composition_binding_activates_it_end_to_end(self, tmp_path):
        """Reachability: the value must reach the binding from a real
        composition, not only from a hand-held string.
        """
        from tests.helpers.composed_manifest import write_complete_manifest
        from workflows.task_composition import (
            active_composition_fingerprint,
            bind_run_task_composition,
            compose_run_task_bindings,
        )

        composition = compose_run_task_bindings(str(write_complete_manifest(tmp_path)))
        with bind_run_task_composition(composition, physical_data_root=str(REPO_ROOT)):
            assert active_composition_fingerprint() == composition.semantic_fingerprint
        assert active_composition_fingerprint() is None

    def test_the_record_and_output_stamps_share_ONE_authority(self):
        """**Gate-2 regression.** The real composed Gate run produced records
        correctly stamped `d6628a93…` and an OUTPUT stamped `None`.

        The output stamp read `bindings.task_composition_fingerprint`, which
        comes from the TUNER's own sub-workspace lock — and that lock does not
        carry the composition (carried Step-10 debt **F-P56-3**: "composition
        kwargs reach only the chain-level invariants lock"). Post-C8 that is
        not cosmetic: a composed 2-iteration chain would have refused its own
        iteration-1 OUTPUT at ingress under R-11-9 case 3.

        Both stamps now read the SAME run-scoped authority, so they cannot
        disagree at all.
        """
        import ast

        src = (REPO_ROOT / "nodes/ml_hyperparameter_tune_agent/records.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(src)
        calls = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "active_composition_fingerprint"
        ]
        assert len(calls) == 2, (
            "the record stamp and the output stamp must BOTH read the "
            f"run-scoped authority; found {len(calls)} call site(s)"
        )
        # AST, not substring: the explanatory comment above the fix NAMES
        # `bindings.task_composition_fingerprint`, and counting prose as code
        # is the mistake this PR has already made twice.
        reads = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Attribute)
            and n.attr == "task_composition_fingerprint"
            and isinstance(n.value, ast.Name)
            and n.value.id == "bindings"
        ]
        assert reads == [], (
            "the output stamp must not read the tuner's own lock — it does "
            "not carry the composition (F-P56-3)"
        )

    def test_a_stamped_record_round_trips_through_the_validator(self, tmp_path):
        """The full loop: a composed run stamps, and its own record passes
        the ingress it would otherwise be refused by.
        """
        from tests.helpers.composed_manifest import write_complete_manifest
        from workflows.task_composition import (
            active_composition_fingerprint,
            bind_run_task_composition,
            compose_run_task_bindings,
        )

        composition = compose_run_task_bindings(str(write_complete_manifest(tmp_path)))
        with bind_run_task_composition(composition, physical_data_root=str(REPO_ROOT)):
            record = _stamped(task_composition_fingerprint=active_composition_fingerprint())
        validate_stamped_invariants(
            record,
            _invariants(task_composition_fingerprint=composition.semantic_fingerprint),
            full_scope=FULL_SCOPE,
            source="the composed run's own record",
        )
