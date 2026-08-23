"""Step 12 / PR-12bc — B1: the optional scope capability and its request carrier.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12bc_generic_task_boundary_closure.md`` §D.1, §M / B1; ledger §Q.B1.

Contracts only. No implementation is wired, no call site changes, and the
frozen four-method ``TaskDataPath`` protocol body is untouched. What this
module owns:

* **the frozen four-method contract is not amended** (Q-12-2 = A) — asserted
  against the protocol's own method tuple, not by reading the diff;
* **``ScopeBuildRequest`` carries zero task vocabulary** — a census over its
  DECLARED FIELDS, so a future field named ``seg_size`` or ``profile`` fails
  here rather than in review;
* **the capability-absent refusal is named and fail-closed**, raised
  parent-side at composition and naming both the id and every missing method;
* **partial declaration is refusal, not partial capability** — three of four
  methods is the case an ``isinstance`` check against a runtime-checkable
  Protocol would get wrong in the other direction, so it is asserted;
* **backward compatibility** — an implementation declaring no capability
  still registers and resolves exactly as before.

What is NOT tested here, deliberately: that ``ScopeBuildRequest`` rejects an
unknown ``Literal`` value or that an optional field defaults to ``None``.
Pydantic's own declaration enforces both, and CLAUDE.md forbids pytesting what
a declaration already guarantees. The bounds that ARE asserted below
(``portion`` half-open at 0, ``max_samples >= 1``) are cross-checked because
they encode a semantic — a zero portion selects nothing and a zero ceiling
would silently mean "no samples" rather than "no ceiling".
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from execute_tools.task_data_path import (
    _PROTOCOL_METHODS,
    _SCOPE_CAPABILITY_METHODS,
    EpochSamplingParams,
    ScopeBuildRequest,
    TaskScopeCapability,
    TaskScopeCapabilityError,
    declares_scope_capability,
    register_task_data_path,
    resolve_task_scope_capability,
)

# ----------------------------------------------------------------------
# Stubs — deliberately minimal, and NOT registered unless a test says so.
# ----------------------------------------------------------------------


class _NoCapability:
    """A perfectly valid four-method data path that declares no capability."""

    task_data_path_id = "b1_no_capability"

    def training_dataset(self, scope, params):  # pragma: no cover - never called
        raise AssertionError("B1 wires nothing")

    def validation_dataset(self, scope, params):  # pragma: no cover
        raise AssertionError("B1 wires nothing")

    def write_deliverable(self, outputs, request):  # pragma: no cover
        raise AssertionError("B1 wires nothing")

    def read_evaluation_payload(self, request):  # pragma: no cover
        raise AssertionError("B1 wires nothing")


class _WithCapability(_NoCapability):
    task_data_path_id = "b1_with_capability"

    def build_training_scope(self, request):
        return ("train", request.round_kind, request.portion)

    def build_eval_scope(self, request):
        return ("eval", request.round_kind, request.portion)

    def serialize_scope(self, scope):
        return repr(scope)

    def deserialize_scope(self, payload):
        return payload


class _PartialCapability(_NoCapability):
    """Three of the four. The case a presence-only check gets wrong."""

    task_data_path_id = "b1_partial_capability"

    def build_training_scope(self, request):  # pragma: no cover
        raise AssertionError("never reached")

    def build_eval_scope(self, request):  # pragma: no cover
        raise AssertionError("never reached")

    def serialize_scope(self, scope):  # pragma: no cover
        raise AssertionError("never reached")

    # deserialize_scope deliberately absent.


class _NonCallableAttribute(_NoCapability):
    """Declares all four NAMES; one is not callable."""

    task_data_path_id = "b1_non_callable"
    build_training_scope = "not a method"

    def build_eval_scope(self, request):  # pragma: no cover
        raise AssertionError("never reached")

    def serialize_scope(self, scope):  # pragma: no cover
        raise AssertionError("never reached")

    def deserialize_scope(self, payload):  # pragma: no cover
        raise AssertionError("never reached")


REQUEST = ScopeBuildRequest(round_kind="trial", selection_strategy="snapshot", portion=0.1)


# ======================================================================
# The frozen contract is NOT amended
# ======================================================================


class TestTheFourMethodContractIsUntouched:
    def test_task_data_path_still_declares_exactly_four_methods(self):
        """Q-12-2 = A. Asserted against the tuple the registry validates
        against, so an added fifth method fails here even if the Protocol body
        and the tuple were edited together.
        """
        assert _PROTOCOL_METHODS == (
            "training_dataset",
            "validation_dataset",
            "write_deliverable",
            "read_evaluation_payload",
        )

    def test_the_capability_is_a_disjoint_sibling_set(self):
        assert _SCOPE_CAPABILITY_METHODS == (
            "build_training_scope",
            "build_eval_scope",
            "serialize_scope",
            "deserialize_scope",
        )
        assert set(_SCOPE_CAPABILITY_METHODS).isdisjoint(_PROTOCOL_METHODS), (
            "a capability method collided with a frozen contract method — the "
            "sibling would then be amending the contract by the back door"
        )

    def test_registration_never_requires_the_capability(self):
        """Backward compatibility, at the edge that would break first."""
        register_task_data_path(_NoCapability())  # must not raise


# ======================================================================
# ScopeBuildRequest carries FRAMEWORK vocabulary only
# ======================================================================

#: Substrings that would mean task vocabulary had been smuggled in. Drawn from
#: what the three known tasks actually call things, plus the geometry words
#: ``EpochSamplingParams``' own docstring names as deliberately absent.
TASK_VOCABULARY_MARKERS = (
    "seg",
    "psd",
    "channel",
    "file_name",
    "pattern",
    "profile",
    "dataset",
    "h5",
    "sampling_frequency",
    "clip",
    "frame",
    "row",
    "class",
    "image",
)


class TestTheRequestCarriesNoTaskVocabulary:
    def test_the_declared_field_set_is_exactly_the_audited_one(self):
        """Hardcoded, never read back from the model. A field added without
        an audit entry fails here.

        ``task_parameters`` was added at B3 as a RECORDED extension of D-BC-1
        (§Q.B3): D-BC-1 derived this carrier from where trial and formal
        DIFFER, and a per-attempt value that is the same in both rounds is
        exactly what that method cannot see — TIDMAD's scope needs
        ``seg_size``, the planner's model choice, which every round needs and
        neither varies. It is task vocabulary, so it can only ride OPAQUELY.
        """
        assert set(ScopeBuildRequest.model_fields) == {
            "round_kind",
            "selection_strategy",
            "portion",
            "seed",
            "max_samples",
            "target_partitions",
            "subset_ref",
            "task_parameters",
        }

    def test_the_opaque_payload_is_never_interpreted_by_the_carrier(self):
        """Opacity is a property of the FRAMEWORK: the carrier accepts any
        mapping and validates none of its contents, exactly as ``subset_ref``
        accepts any string. A carrier that started type-checking a key would
        be the framework reading task vocabulary.
        """
        weird = {"seg_size": 10_000, "anything": [1, {"nested": None}]}
        assert (
            ScopeBuildRequest(
                round_kind="trial",
                selection_strategy="snapshot",
                portion=0.1,
                task_parameters=weird,
            ).task_parameters
            == weird
        )

    @pytest.mark.parametrize("marker", TASK_VOCABULARY_MARKERS)
    def test_no_field_name_carries_task_vocabulary(self, marker):
        """The census the design asks for: over FIELDS, not by inspection.

        ``EpochSamplingParams`` states the rule this enforces — "Task-vocabulary
        values ... are deliberately ABSENT" (``task_data_path.py:99-104``).
        """
        offenders = [f for f in ScopeBuildRequest.model_fields if marker in f]
        assert offenders == [], (
            f"ScopeBuildRequest field(s) {offenders} carry task vocabulary "
            f"({marker!r}). A task obtains its own vocabulary through its own "
            f"authorities; this carrier holds framework selection knobs only."
        )

    def test_the_sibling_carrier_obeys_the_same_rule(self):
        """Stated over BOTH carriers, so the rule is the concept's and not
        this one type's. ``data_dir`` is a framework-level location, not task
        vocabulary, and is the reason the marker list has no ``dir``.
        """
        for marker in TASK_VOCABULARY_MARKERS:
            assert [f for f in EpochSamplingParams.model_fields if marker in f] == []

    def test_the_profile_is_deliberately_absent(self):
        """The single strongest anti-smuggling statement: a task that needs
        its topology already holds it.
        """
        assert "profile" not in ScopeBuildRequest.model_fields

    def test_there_is_no_leg_field(self):
        """The leg is expressed by WHICH METHOD is called. A field would let a
        caller ask ``build_training_scope`` for an eval scope.
        """
        for name in ("leg", "kind", "is_eval", "phase"):
            assert name not in ScopeBuildRequest.model_fields

    def test_the_carrier_is_frozen_and_forbids_extras(self):
        with pytest.raises(ValidationError):
            ScopeBuildRequest(
                round_kind="trial", selection_strategy="snapshot", portion=0.1, seg_size=10
            )
        with pytest.raises(ValidationError):
            REQUEST.portion = 0.5  # type: ignore[misc]


class TestTheSemanticBounds:
    """Bounds that encode a meaning, not bounds a type already gives."""

    @pytest.mark.parametrize("bad", [0.0, -0.1, 1.5])
    def test_portion_must_be_a_real_fraction(self, bad):
        """A zero portion selects nothing; above 1.0 is not a fraction."""
        with pytest.raises(ValidationError):
            ScopeBuildRequest(round_kind="trial", selection_strategy="snapshot", portion=bad)

    def test_a_zero_ceiling_is_refused_rather_than_meaning_unbounded(self):
        """``None`` means "no ceiling". ``0`` must not quietly become a synonym
        for it, nor silently mean "no samples".
        """
        with pytest.raises(ValidationError):
            ScopeBuildRequest(
                round_kind="trial",
                selection_strategy="snapshot",
                portion=0.1,
                max_samples=0,
            )

    def test_the_opaque_subset_ref_is_never_parsed_here(self):
        """Opacity is a property of the FRAMEWORK, so the carrier accepts any
        string and validates none of it. The task interprets it.
        """
        weird = "not-a-data-scope::{}[]"
        assert (
            ScopeBuildRequest(
                round_kind="formal",
                selection_strategy="snapshot",
                portion=1.0,
                subset_ref=weird,
            ).subset_ref
            == weird
        )


# ======================================================================
# The capability-absent refusal
# ======================================================================


class TestCapabilityResolution:
    def test_a_declaring_implementation_resolves(self):
        impl = _WithCapability()
        assert declares_scope_capability(impl) is True
        assert resolve_task_scope_capability(impl) is impl

    def test_absent_capability_refuses_naming_id_and_every_missing_method(self):
        with pytest.raises(TaskScopeCapabilityError) as exc:
            resolve_task_scope_capability(_NoCapability())
        msg = str(exc.value)
        assert "b1_no_capability" in msg
        for method in _SCOPE_CAPABILITY_METHODS:
            assert method in msg, f"the refusal does not name the missing {method!r}"

    def test_partial_declaration_is_refusal_not_partial_capability(self):
        """Three of four. The refusal must name the ONE that is missing and
        not the three that are present, or an operator fixes the wrong thing.
        """
        with pytest.raises(TaskScopeCapabilityError) as exc:
            resolve_task_scope_capability(_PartialCapability())
        msg = str(exc.value)
        assert "missing ['deserialize_scope']" in msg
        assert declares_scope_capability(_PartialCapability()) is False

    def test_a_non_callable_attribute_of_the_right_name_is_refused(self):
        """Why the check is CALLABILITY, not ``isinstance`` against the
        runtime-checkable Protocol: that only checks attribute PRESENCE and
        would accept this class.
        """
        impl = _NonCallableAttribute()
        assert isinstance(impl, TaskScopeCapability), (
            "precondition of this test: the Protocol's own isinstance accepts "
            "a non-callable attribute — which is exactly why production does "
            "not use it"
        )
        assert declares_scope_capability(impl) is False
        with pytest.raises(TaskScopeCapabilityError, match="build_training_scope"):
            resolve_task_scope_capability(impl)

    def test_the_refusal_says_it_happened_before_any_subprocess(self):
        """The design's requirement is WHEN, not merely THAT: fail closed at
        composition, never at first spawn. The message carries that promise,
        so an operator reading a log knows no GPU minute was spent.
        """
        with pytest.raises(TaskScopeCapabilityError) as exc:
            resolve_task_scope_capability(_NoCapability())
        assert "before any subprocess was launched" in str(exc.value)

    def test_it_is_not_a_resolution_error(self):
        """The binding resolved fine; an optional sibling is absent. Conflating
        the two makes both messages worse.
        """
        from execute_tools.task_data_path import TaskDataPathResolutionError

        with pytest.raises(TaskScopeCapabilityError) as exc:
            resolve_task_scope_capability(_NoCapability())
        assert not isinstance(exc.value, TaskDataPathResolutionError)


# ``TestNothingIsWiredYet`` was RETIRED (R-11-10).
#
# It pinned B1's "the refusal exists but no production caller can reach it"
# half with a `git grep` census, and it fired with exactly its intended message
# the moment B5 wired `acquire_attempt_scopes`. A flipped guard becomes the
# permanent owner of the corrected property or is deleted, never both — and the
# positive contract (a composed run's scopes come from the bound capability,
# and a capability-absent composed run is refused parent-side) is owned by
#
#     tests/unit/nodes/ml_hyperparameter_tune_agent/
#         test_step12_pr12bc_b5_scope_acquisition.py
#
# so this one is deleted rather than twinned. Recorded in the ledger at §Q.B6:
# it should have been retired IN the B5 commit; B5's targeted run covered the
# node suites and not this module, which is how it survived one commit longer
# than it should have.
