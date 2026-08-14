"""Step 04a — the normalized Model-I/O contract must survive the impl->valid hop.

Design: ``docs/design/generic_framework_upgrade/step_04_candidate_creation_mechanics/
pr_04a_contract_derived_candidate_mechanics.md`` §15.1 (the four-row
behavioural contract) and §16 C2.

**The defect only this module catches.** The validator is about to derive
its probe's class extent, rank and axis roles from a contract it receives
through this hop. A hop that silently drops the contract does not crash —
it hands the validator ``None``, the legacy path takes over, and every
candidate is probed against TIDMAD's ``256`` regardless of what the task
declared. Under TIDMAD that is invisible: the legacy fallback and the
derivation agree, so every existing test stays green while the transport is
severed. The V21 PR-E post-mortem recorded the same shape — a field arrived
at a subprocess that then never used it.

So the assertions here are deliberately **by value**, never
``is not None``: §16's binding principle is *assert the observable artifact,
never the configuration value*, and "a contract is present" is satisfied by
any contract, including a wrong one substituted en route.

Row coverage (§15.1):

===  ==========================================  =========================
row  situation                                   test
===  ==========================================  =========================
1    legacy caller, no contract                   ``test_absent_contract_..``
2    contract supplied -> authoritative           ``test_explicit_contract_..``
4    contract dropped/substituted in transit      ``test_a_dropped_contract..``
===  ==========================================  =========================

Row 3 (explicit but incomplete -> typed fail-closed) is a *consumer*
property, not a transport one, and is proven at the probe in C3.
"""

from __future__ import annotations

import pytest

from agent.schemas.implementor import ImplementorOutput
from agent.schemas.protocols.ml_model_impl_to_ml_model_valid import local_all_fields
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from tests.helpers.step04a_fixtures import regressor_model_io, tidmad_model_io


@pytest.fixture
def storage():
    return StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace="/tmp/s04a_transport", run_name="r1"),
    )


def _output(model_io):
    return ImplementorOutput(
        model_type="s04a_transport_probe",
        model_file_path="/abs/models/s04a_transport_probe.py",
        test_file_path="/abs/tests/test_s04a_transport_probe.py",
        description_file_path="/abs/models/s04a_transport_probe/description.md",
        config_fields={"channels": 16},
        model_description="transport probe",
        mathematical_definition="transport probe",
        model_io_contract=model_io,
    )


@pytest.mark.parametrize(
    ("label", "contract"),
    [("tidmad", tidmad_model_io()), ("regressor", regressor_model_io())],
)
def test_explicit_contract_arrives_unchanged_by_value(storage, label, contract):
    """The declaration reaching the validator EQUALS the one upstream held.

    Fails when: the protocol re-resolves, defaults, or substitutes the
    contract. Equality is on the whole model, so a hop that preserved the
    output tensor but dropped the input dtype admissibility also reds.
    """
    arrived = local_all_fields(_output(contract), storage).model_io_contract
    assert arrived == contract, f"{label}: contract mutated in transit"

    # And the semantics the probe will actually read, spelled out — so a
    # future change that keeps the object equal but breaks the derived
    # properties still fails here rather than at a probe three commits later.
    assert arrived is not None
    assert arrived.class_cardinality == contract.class_cardinality
    assert arrived.output_semantic is contract.output_semantic


def test_absent_contract_maps_to_none_without_raising(storage):
    """§15.1 row 1: absence is the legacy path, not an error.

    Fails when: anyone makes the field required, or substitutes a shipped
    TIDMAD contract for a caller that never declared one — which would turn
    every legacy caller into a silently TIDMAD-bound one.
    """
    arrived = local_all_fields(_output(None), storage)
    assert arrived.model_io_contract is None


def test_a_dropped_contract_is_detectable_not_silent(storage):
    """§15.1 row 4, stated as the mutation this suite must catch.

    This is the reachability assertion: it compares what the validator
    receives against what the implementor emitted, for a contract whose
    cardinality is deliberately NOT TIDMAD's. Delete the
    ``model_io_contract=output.model_io_contract`` line from
    ``local_all_fields`` and this test reds, while a test asserting only
    "the field is not None" would too — but a test asserting TIDMAD values
    would not, because the legacy fallback produces them anyway. 16 is
    chosen for exactly that reason.
    """
    emitted = tidmad_model_io(num_classes=16)
    output = _output(emitted)

    received = local_all_fields(output, storage).model_io_contract

    assert received is not None, "the contract was dropped in transit"
    assert received.class_cardinality == 16, (
        "the validator received a different cardinality than the implementor "
        f"declared ({received.class_cardinality} != 16) — a substituted or "
        "re-resolved contract, which §15.1 row 4 forbids"
    )
    assert received == output.model_io_contract
