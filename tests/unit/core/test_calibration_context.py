"""One definition of the calibration identity context, used by both sides.

V20 PR C1 / C-C5b.

`candidate_config_hash` is `config_hash12` over this mapping, so the training
engine (which records what it ran) and the pre-launch time gate (which asks
what was recorded) must produce byte-identical output. A one-key or
one-expression drift makes every lookup miss, and a miss is indistinguishable
from "nothing recorded yet" -- the subsystem reports no error and silently
never matches.

The parity test below is the load-bearing one: it pins the exact mapping the
engine produced BEFORE this module existed, so the refactor cannot have moved
any already-stored identity.
"""

from __future__ import annotations

import pytest

from core.runtime_control.calibration_context import (
    CalibrationContextInputs,
    build_calibration_context,
    model_precision,
    trainable_param_count,
    training_loop_runtime_flags,
)
from core.runtime_control.identity import config_hash12

INPUTS = CalibrationContextInputs(
    precision="float32",
    optimizer_type="adamw",
    model_family="wavenet",
    param_count=156_320,
    seg_size=40_000,
    batch_size=8,
)

#: The literal mapping `train_engine_sandbox.py` built inline before C-C5b,
#: transcribed from the pre-refactor source. Hardcoded on purpose: reading it
#: back from the thing under test would compare the code to itself.
PRE_REFACTOR = {
    "precision": "float32",
    "optimizer_type": "adamw",
    "model_family": "wavenet",
    "param_count": 156_320,
    "seg_size": 40_000,
    "batch_size": 8,
    "runtime_flags": {
        "num_workers": 0,
        "pin_memory": False,
        "grad_accumulation": False,
        "torch_compile": False,
    },
}


class TestTheRefactorMovedNoStoredIdentity:
    def test_the_context_matches_the_pre_refactor_mapping(self):
        assert build_calibration_context(INPUTS) == PRE_REFACTOR

    def test_the_hash_is_unchanged(self):
        """The value that actually travels into `candidate_config_hash`. If
        this moved, every record written before C-C5b would stop matching
        and the registry's existing evidence would be orphaned."""
        assert config_hash12(build_calibration_context(INPUTS)) == config_hash12(PRE_REFACTOR)


class TestBothSidesCountParametersTheSameWay:
    """The divergence this module was written to remove.

    The engine counted `requires_grad` parameters; the pre-flight counted
    all of them. Identical for a fully-trainable model, silently different
    for any model with a frozen layer -- so calibration would never apply to
    exactly those candidates, with nothing to indicate why.
    """

    def test_frozen_parameters_are_excluded(self):
        torch = pytest.importorskip("torch")

        model = torch.nn.Sequential(torch.nn.Linear(4, 4, bias=False))
        assert trainable_param_count(model) == 16

        for param in model.parameters():
            param.requires_grad = False
        assert trainable_param_count(model) == 0, (
            "a frozen parameter still counted as trainable; the engine and "
            "the pre-flight would hash different identities for this model"
        )

    def test_precision_is_spelled_as_the_record_spells_it(self):
        torch = pytest.importorskip("torch")

        model = torch.nn.Linear(2, 2)
        assert model_precision(model) == "float32"
        assert "torch." not in model_precision(model)


class TestRuntimeFlagsAreConstantsNotMeasurements:
    def test_the_flags_describe_the_production_loop(self):
        """Pinned so that changing the training loop without updating this
        definition fails here rather than silently splitting the bucket."""
        assert training_loop_runtime_flags() == {
            "num_workers": 0,
            "pin_memory": False,
            "grad_accumulation": False,
            "torch_compile": False,
        }

    def test_a_fresh_mapping_is_returned_each_call(self):
        """A shared mutable default would let one caller's edit alter every
        subsequent identity."""
        first = training_loop_runtime_flags()
        first["num_workers"] = 99
        assert training_loop_runtime_flags()["num_workers"] == 0


class TestTheInputsRefuseUnusableValues:
    @pytest.mark.parametrize(
        "field,value",
        [("param_count", 0), ("seg_size", 0), ("batch_size", 0), ("precision", "")],
    )
    def test_a_meaningless_value_is_refused(self, field, value):
        """These are identity components. A zero batch size or blank
        precision would produce a hash for a configuration that cannot
        exist, and it would collide with every other such mistake."""
        from pydantic import ValidationError

        payload = {**INPUTS.model_dump(), field: value}
        with pytest.raises(ValidationError):
            CalibrationContextInputs(**payload)


class TestTheEnvelopeVocabularyFollowsTheEvidence:
    """Producers spell the workload differently, and a hardcoded reader
    vocabulary silently excludes whichever one it does not name.

    C-C3c derived records carry `seg_size`; probe records carry
    `segment_length`. An envelope built over a fixed list finds no range for
    the other, fails closed on it, and never matches -- which looks exactly
    like an empty registry. This asserts the reader derives its dimensions
    from the evidence instead.
    """

    def test_both_producer_vocabularies_yield_ranges(self):
        from core.runtime_control.calibration_registry import _measured_dimensions

        class _Obs:
            def __init__(self, workload):
                self.workload = workload

        derived = _Obs({"batch_size": 8, "seg_size": 40_000, "param_count": 156_320})
        probe = _Obs({"batch_size": 8, "segment_length": 40_000, "steps": 3125})

        assert "seg_size" in _measured_dimensions([derived])
        assert "segment_length" in _measured_dimensions([probe])

    def test_non_numeric_workload_values_are_not_dimensions(self):
        """A range needs numbers. A string sneaking in would make
        `min`/`max` compare incomparable types at read time."""
        from core.runtime_control.calibration_registry import _measured_dimensions

        class _Obs:
            def __init__(self):
                self.workload = {"batch_size": 8, "device": "cuda:0", "notes": None}

        assert _measured_dimensions([_Obs()]) == ("batch_size",)

    def test_the_derived_writer_vocabulary_is_declared_once(self):
        """The write side names its keys in one place, so a new dimension is
        added where the record is built rather than in a reader's guess."""
        from core.runtime_control.calibration_derivation import DERIVED_WORKLOAD_DIMENSIONS

        assert DERIVED_WORKLOAD_DIMENSIONS == ("batch_size", "seg_size", "param_count")
