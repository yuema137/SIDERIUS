"""Compatible loss inventory and task-owned validation-provider boundaries."""

from types import SimpleNamespace

import pytest
import torch

from agent.schemas.custom_loss_contract import (
    ExplicitPairApplicability,
    build_custom_loss_contract_snapshot,
    resolve_custom_loss_inventory,
    resolve_custom_loss_validation_pair_provider,
)
from agent.schemas.model_io_contract import Dimension, TensorAxis, TensorContract
from core.capability_registry import CapabilityContractSnapshot, CapabilityMetadata
from ml_models.models_format_sandbox import DtypeAdmissibility


def _tensor(*dims: int | str, dtype: str = "float32") -> TensorContract:
    return TensorContract(
        axes=tuple(
            TensorAxis(
                dimension=Dimension(fixed=dim) if isinstance(dim, int) else Dimension(symbolic=dim)
            )
            for dim in dims
        ),
        dtype=DtypeAdmissibility(admissible=(dtype,)),
    )


def _metadata(
    name: str,
    snapshot: CapabilityContractSnapshot | None,
) -> CapabilityMetadata:
    return CapabilityMetadata(
        name=name,
        capability_type="loss",
        file_path=f"/{name}.py",
        created_at="2026-09-14T00:00:00Z",
        contract_snapshot=snapshot,
    )


def _contract_fixture():
    prediction = _tensor("B", 1)
    target = _tensor("B", 2)
    applicability = ExplicitPairApplicability(prediction=prediction, target=target)
    snapshot = build_custom_loss_contract_snapshot(prediction, target, applicability)
    projection = SimpleNamespace(
        supervision_target=target,
        custom_loss_applicability=applicability,
    )
    return prediction, target, applicability, snapshot, projection


def test_uncomposed_inventory_preserves_loadable_order_without_contract_filtering():
    rows = (_metadata("legacy_a", None), _metadata("legacy_b", None))

    inventory = resolve_custom_loss_inventory(rows)

    assert not inventory.composed
    assert inventory.names == ("legacy_a", "legacy_b")
    assert inventory.unavailable == ()


def test_composed_inventory_retains_only_the_exact_snapshot_with_named_refusals():
    prediction, target, applicability, expected, projection = _contract_fixture()
    mismatch = build_custom_loss_contract_snapshot(_tensor("B", 3), target, applicability)
    wrong_kind = CapabilityContractSnapshot(
        contract_kind="other-owner",
        contract_version=1,
        canonical_payload="{}",
        sha256="44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
    )
    rows = (
        _metadata("exact", expected),
        _metadata("missing", None),
        _metadata("mismatch", mismatch),
        _metadata("wrong_kind", wrong_kind),
    )

    inventory = resolve_custom_loss_inventory(rows, expected, projection)

    assert inventory.names == ("exact",)
    refusals = {item.name: item.reason for item in inventory.unavailable}
    assert "missing" in refusals and "missing" in refusals["missing"]
    assert "mismatch" in refusals and "does not match" in refusals["mismatch"]
    assert "wrong_kind" in refusals and "malformed" in refusals["wrong_kind"]
    assert prediction == applicability.prediction


def test_projection_disagreement_makes_the_composed_inventory_unavailable():
    _, _, _, expected, projection = _contract_fixture()
    projection.supervision_target = _tensor("B", 3)

    inventory = resolve_custom_loss_inventory(
        (_metadata("candidate", expected),),
        expected,
        projection,
    )

    assert inventory.names == ()
    assert inventory.unavailable_reason == (
        "task projection disagrees with expected custom-loss snapshot"
    )
    assert inventory.unavailable[0].name == "candidate"
    assert "projection disagrees" in inventory.unavailable[0].reason


def test_empty_composed_inventory_still_reports_missing_contract_authority():
    *_, projection = _contract_fixture()

    inventory = resolve_custom_loss_inventory((), None, projection)

    assert inventory.composed
    assert inventory.names == ()
    assert inventory.unavailable == ()
    assert inventory.unavailable_reason == "expected custom-loss snapshot is missing"


def test_empty_valid_composed_inventory_names_absent_loadable_losses():
    *_, expected, projection = _contract_fixture()

    inventory = resolve_custom_loss_inventory((), expected, projection)

    assert inventory.composed
    assert inventory.names == ()
    assert inventory.unavailable == ()
    assert inventory.unavailable_reason == "no loadable custom losses are registered"


def test_locked_builtin_hides_compatible_custom_losses():
    *_, expected, projection = _contract_fixture()
    projection.objective = SimpleNamespace(loss_type="ce", loss_name=None)

    inventory = resolve_custom_loss_inventory(
        (_metadata("compatible", expected),), expected, projection
    )

    assert inventory.names == ()
    assert inventory.unavailable_reason == "task objective is locked to builtin loss 'ce'"
    assert not inventory.generation_allowed


def test_locked_custom_exposes_only_its_exact_compatible_loss():
    *_, expected, projection = _contract_fixture()
    projection.objective = SimpleNamespace(loss_type="custom", loss_name="required")

    inventory = resolve_custom_loss_inventory(
        (_metadata("other", expected), _metadata("required", expected)),
        expected,
        projection,
    )

    assert inventory.names == ("required",)
    assert {item.name for item in inventory.unavailable} == {"other"}
    assert inventory.unavailable_reason == "task objective is locked to custom loss 'required'"
    assert not inventory.generation_allowed


def test_locked_custom_missing_exact_loss_refuses_before_callers_can_act():
    *_, expected, projection = _contract_fixture()
    projection.objective = SimpleNamespace(loss_type="custom", loss_name="required")

    with pytest.raises(ValueError, match="locked custom objective 'required' is unavailable"):
        resolve_custom_loss_inventory(
            (_metadata("other", expected),),
            expected,
            projection,
        )


def test_provider_resolution_is_optional_and_never_touches_data_methods():
    class TaskImplementation:
        calls = 0

        def custom_loss_validation_pair(self):
            self.calls += 1
            return torch.zeros(1, 1), torch.zeros(1, 1)

        def training_dataset(self):
            raise AssertionError("provider resolution touched training data")

        def validation_dataset(self):
            raise AssertionError("provider resolution touched validation data")

        def build_sample_set(self):
            raise AssertionError("provider resolution touched sample scope")

        def task_probe_data(self):
            raise AssertionError("provider resolution touched probe data")

    implementation = TaskImplementation()
    provider = resolve_custom_loss_validation_pair_provider(implementation)

    assert provider is not None
    assert implementation.calls == 0
    assert resolve_custom_loss_validation_pair_provider(object()) is None


def test_non_callable_provider_is_a_named_contract_refusal():
    with pytest.raises(ValueError, match="present but not callable"):
        resolve_custom_loss_validation_pair_provider(
            SimpleNamespace(custom_loss_validation_pair="not-a-function")
        )
