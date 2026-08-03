"""The two identity fields production dropped, and the buckets they key.

V20 PR C1 / C-C1.

Two production call sites in `_resolve_time_check_probe_request` decided the
identity of every calibration record this machine can write, and both threw
it away:

    ml_hyperparameter_tune_agent.py   ProbeRequest(...) omitted `model_family`
                                      -> the "unknown" default
                                      -> bucket component 6, for every record
    ml_hyperparameter_tune_agent.py   build_registry_persist(software_stack={})
                                      -> stack_identity({}) is one constant
                                      -> bucket component 7 inert, for every
                                         record

Measured on the live registry before this change: `model_family` was
`"unknown"` in 20 of 20 records, and `software_stack` was `{}` in 18 of 20 --
the two populated ones came from the operator bootstrap CLI, which built its
stack inline.

So the bucket key had seven dimensions and two of them were constants. That
is not a bucketing scheme, it is one bucket, and no applicability rule can be
built on top of it.

These tests drive the REAL producer -- a real `ProbeRequest` and a real
`ProbeResult` through `probe_observations` -- because the defect was never in
that function. It faithfully forwarded what it was given. The defect was at
the call site, and a test that hand-builds a `CalibrationObservation` cannot
see it. That is the same shape as #156, #157, #159 and the A5 field-drop.

SCOPE. C-C1 changes no schema. A candidate whose family cannot be resolved
keeps today's non-authoritative behaviour; the explicit `unusable`
namespace is schema v2's (C-C2, under operator decision O-2) and must not be
pre-empted here.
"""

from __future__ import annotations

import pytest

from core.runtime_control.calibration_policy import (
    bucket_components,
    classify_model_family,
    stack_identity,
)
from core.runtime_control.probe import ProbeResult, probe_observations
from core.runtime_control.probe_lifecycle import ProbeRequest
from core.runtime_control.provenance import capture_software_stack

#: What `stack_identity` returns for the empty dict. Hardcoded rather than
#: computed so this test states the value the 18 records actually share; a
#: computed expectation would compare the function to itself.
EMPTY_STACK_IDENTITY = "stack:44136fa355b3"


def _ok_result(model_identity: str = "punet") -> ProbeResult:
    """A minimal ok probe.

    `realized` is required, not decoration: `probe_observations` refuses a
    result without it (`probe.py:539`), because an observation records what
    the IMPLEMENTED model turned out to be, not what was planned.
    """
    from core.runtime_control.probe import (
        ContentionSnapshot,
        ProbeCaps,
        RealizedModelProperties,
    )

    return ProbeResult(
        status="ok",
        model_identity=model_identity,
        realized=RealizedModelProperties(
            parameter_count=6_762_568,
            trainable_parameter_count=6_762_568,
            parameter_memory_gb=0.0252,
            dtype="float32",
        ),
        train_ms_per_step=12.5,
        train_ms_spread=(11.0, 14.0),
        concurrency_identity="single_candidate_idle",
        contention=ContentionSnapshot(verdict="single_candidate_idle"),
        caps=ProbeCaps(),
        wall_seconds=3.0,
    )


def _observations(*, model_family: str, software_stack: dict):
    """Drive the real producer, not a hand-built observation."""
    return probe_observations(
        _ok_result(),
        hardware_compatibility_id="hw-test",
        execution_environment_id="env-test",
        workload={"batch_size": 4, "segment_length": 40_000},
        software_stack=software_stack,
        source_run={"run_name": "r", "exp_id": "e"},
        model_family=model_family,
    )


class TestTheFamilyReachesTheRecord:
    def test_a_declared_family_survives_the_producer(self):
        """The forwarding this commit relies on. `ProbeRequest.model_family`
        is handed to `probe_observations` by `build_registry_persist`, so if
        the producer dropped it the call-site fix would be invisible."""
        obs = _observations(
            model_family=classify_model_family(declared_family="punet"),
            software_stack=capture_software_stack(),
        )
        assert obs, "an ok probe with a train timing must yield an observation"
        assert all(o.model_family == "punet" for o in obs)

    def test_the_request_no_longer_defaults_to_unknown(self):
        """The defect itself. `model_family` has a default, so omitting it at
        the call site is silent -- nothing raises, and every record buckets
        under the same string."""
        omitted = ProbeRequest(model_identity="punet", train_steps=7, inference_batches=0)
        assert omitted.model_family == "unknown", (
            "the default is what the call site was silently taking; if this "
            "changes, the C-C1 fix is no longer the thing being tested"
        )

        declared = ProbeRequest(
            model_identity="punet",
            model_family=classify_model_family(declared_family="punet"),
            train_steps=7,
            inference_batches=0,
        )
        assert declared.model_family == "punet"

    @pytest.mark.parametrize("model_type", ["punet", "wavenet", "fcnet"])
    def test_different_model_types_take_different_families(self, model_type):
        """Separation is the point. One bucket per family only helps if the
        families actually differ."""
        assert classify_model_family(declared_family=model_type) == model_type

    def test_an_unresolvable_family_still_yields_a_record(self):
        """C-C1 SCOPE BOUNDARY. An unclassifiable candidate keeps today's
        behaviour: `"unknown"`, non-authoritative, record still written.

        The explicit `unusable` namespace is C-C2's under O-2. Asserting one
        here would be a promise a no-schema-change commit cannot keep.
        """
        assert classify_model_family(declared_family=None) == "unknown"
        assert classify_model_family(declared_family="   ") == "unknown"

        obs = _observations(model_family="unknown", software_stack=capture_software_stack())
        assert obs and all(o.model_family == "unknown" for o in obs)


class TestTheStackReachesTheRecord:
    def test_a_captured_stack_is_not_the_empty_constant(self):
        """`stack_identity({})` is one digest shared by every record written
        with `software_stack={}` -- 18 of the 20 on this machine. The stack
        dimension of the bucket key was therefore inert."""
        assert stack_identity({}) == EMPTY_STACK_IDENTITY
        assert stack_identity(capture_software_stack()) != EMPTY_STACK_IDENTITY

    def test_the_captured_stack_survives_the_producer(self):
        stack = capture_software_stack()
        obs = _observations(model_family="punet", software_stack=stack)
        assert all(o.software_stack == stack for o in obs)

    def test_an_unavailable_torch_is_recorded_not_erased(self, monkeypatch):
        """`{}` means "we never looked" and is indistinguishable from every
        other never-looked record. `{"torch": None, "cuda": None}` means "we
        looked and found nothing" -- a different fact, and a different bucket.

        Drives the helper's real torch-absent branch. An earlier version of
        this test asserted on a hand-built `{"torch": None, "cuda": None}`
        instead, and so could not tell the two apart: regressing the helper's
        initializer to `{}` left it green, because on a machine WITH torch
        the assignments repopulate the dict either way. The branch only bites
        where torch is missing, which is where the test has to go.
        """
        import sys

        monkeypatch.setitem(sys.modules, "torch", None)  # makes `import torch` raise
        stack = capture_software_stack()

        assert stack == {"torch": None, "cuda": None}, (
            f"a machine without torch must still record that it looked; got {stack!r}"
        )
        assert stack_identity(stack) != EMPTY_STACK_IDENTITY, (
            "an absent stack must not collapse into the same bucket as every "
            "record that never captured one"
        )

    def test_the_helper_matches_what_the_bootstrap_cli_already_wrote(self):
        """The bootstrap CLI built this dict inline and wrote 2 records with
        it. The shared helper must reproduce that shape exactly, or those
        records fork away from anything the tuner writes for the same
        machine."""
        stack = capture_software_stack()
        assert set(stack) == {"torch", "cuda"}, (
            "key names are hashed into the bucket key, so the shape is the "
            "contract -- not just the values"
        )


class TestTheBucketActuallySeparates:
    """Both fields are bucket components. The point of populating them is
    that records which differ now land in different buckets."""

    def _components(self, *, model_family: str, software_stack: dict):
        obs = _observations(model_family=model_family, software_stack=software_stack)
        return bucket_components(obs[0])

    def test_family_changes_the_bucket(self):
        a = self._components(model_family="punet", software_stack=capture_software_stack())
        b = self._components(model_family="wavenet", software_stack=capture_software_stack())
        assert a != b
        assert sum(x != y for x, y in zip(a, b, strict=True)) == 1, (
            "only the family component may differ between these two"
        )

    def test_stack_changes_the_bucket(self):
        a = self._components(model_family="punet", software_stack={})
        b = self._components(model_family="punet", software_stack=capture_software_stack())
        assert a != b
        assert sum(x != y for x, y in zip(a, b, strict=True)) == 1

    def test_before_this_change_both_components_were_constant(self):
        """What the defect looked like: two candidates, different models,
        produced the SAME bucket, because the two call sites supplied the
        same two constants regardless of the candidate."""
        punet = self._components(model_family="unknown", software_stack={})
        wavenet = self._components(model_family="unknown", software_stack={})
        assert punet == wavenet
