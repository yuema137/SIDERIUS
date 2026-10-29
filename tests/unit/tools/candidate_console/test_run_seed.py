"""Issue #983 S6: the console's optional Seed input, review line and readback.

Literal seeds only; every verdict comes from the production review, launch
and read paths. Each test names the defect its assertion owns.
"""

from tests.unit.tools.candidate_console.test_http import client
from tools.candidate_console.seed_labels import readback_label, review_label
from tools.candidate_console.service import seed_readback
from tools.candidate_operations import read_operation
from tools.candidate_operations.store import load_record

#: Above 2**52, so a float round-trip anywhere on the path would corrupt it.
SEED = 4_503_599_627_370_497


def test_wording_distinguishes_operator_generated_and_unrecorded_seeds():
    """Fails if a generated seed reads as operator-chosen (or the reverse), or
    a missing seed reads as a value: the operator could not tell what ran."""
    assert review_label(None) == "Seed: generated at launch"
    assert review_label(SEED) == f"Seed: {SEED} (you set)"
    assert readback_label(SEED, "operator") == f"Seed: {SEED} (you set)"
    assert readback_label(SEED, "generated") == f"Seed: {SEED} (generated)"
    assert readback_label(None, None) == "Seed: unrecorded (pre-seed run)"
    assert readback_label(None, None, native_chain=True).startswith("Seed: not recorded yet")


def test_status_and_list_read_back_the_recorded_seed(prepared):
    """Fails if Status or the operation list omit the admitted seed, mislabel
    its source, or show a value for a pre-seed record."""
    service, chosen, _ = prepared
    store = service.config.operation_store
    recorded = load_record(store, chosen.operation_id).run_seed
    expected = f"Seed: {recorded.value} (generated)"
    api = client(service.config)
    status = api.get(f"/api/operations/{chosen.operation_id}").json()
    assert status["seed"] == expected and status["run_seed"]["value"] == recorded.value
    listed = api.get("/api/operations").json()["operations"][0]
    assert listed["seed"] == expected
    snapshot = read_operation(store, chosen.operation_id)
    assert seed_readback(snapshot.model_copy(update={"run_seed": None})) == (
        "Seed: unrecorded (pre-seed run)"
    )


def test_native_chain_readback_never_shows_a_contradicted_lock_seed(prepared):
    """Fails if a native chain's ``run_seed_anomaly`` is rendered as a seed, or
    if a lock seed is labelled with the wrong source."""
    from tools.candidate_operations.native_chain_models import NativeChainObservation

    service, chosen, _ = prepared
    snapshot = read_operation(service.config.operation_store, chosen.operation_id)

    def chain(**fields):
        observation = NativeChainObservation.model_construct(**fields)
        return seed_readback(snapshot.model_copy(update={"native_chain": observation}))

    assert chain(run_seed=None, run_seed_source=None, run_seed_anomaly=None).startswith(
        "Seed: not recorded yet"
    )
    assert chain(run_seed=SEED, run_seed_source="generated", run_seed_anomaly=None) == (
        f"Seed: {SEED} (generated)"
    )
    contradicted = chain(
        run_seed=None, run_seed_source=None, run_seed_anomaly="lock_contradicts_declaration"
    )
    assert str(SEED) not in contradicted and "contradicts" in contradicted
