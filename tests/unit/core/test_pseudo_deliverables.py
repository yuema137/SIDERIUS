"""Synthetic evidence follows declared geometry, not a fixed task shape."""

import pytest
import torch

from agent.schemas.model_io_contract import ModelIOContract
from core.pseudo_deliverables import PseudoEvidenceUnsupported, SyntheticPredictionModel
from tests.helpers.step04a_fixtures import tidmad_model_io


def test_temporal_logits_vary_within_samples_and_across_calls():
    """A constant-per-sample stub recreates temporal mode-collapse evidence."""
    model = SyntheticPredictionModel(tidmad_model_io())
    first = model(torch.zeros(1, 5, dtype=torch.int64))
    second = model(torch.zeros(1, 5, dtype=torch.int64))
    assert first.shape == (1, 256, 5)
    assert first.argmax(dim=1).tolist() == [[0, 1, 2, 3, 4]]
    assert second.argmax(dim=1).tolist() == [[5, 6, 7, 8, 9]]
    assert first.dtype == torch.float32


def image_contract():
    return ModelIOContract.model_validate(
        {
            "input": {
                "axes": [
                    {"role": "batch", "dimension": {"symbolic": "B"}},
                    {"dimension": {"fixed": 3}},
                ],
                "dtype": {"admissible": ["float32"]},
            },
            "output": {
                "axes": [
                    {"role": "batch", "dimension": {"symbolic": "B"}},
                    {"role": "class", "dimension": {"fixed": 37}},
                ],
                "dtype": {"admissible": ["float64"]},
            },
        }
    )


def test_image_logits_cover_declared_classes_without_rng_or_input_dependence():
    """Batch-one calls must not reset the class counter or assume 256 classes."""
    state = torch.random.get_rng_state()
    model = SyntheticPredictionModel(image_contract())
    predictions = [model(torch.ones(1, 3) * i) for i in range(39)]
    assert [p.argmax(dim=1).item() for p in predictions] == [*range(37), 0, 1]
    assert predictions[0].dtype == torch.float64
    assert torch.equal(state, torch.random.get_rng_state())


def test_unresolvable_output_geometry_has_typed_pseudo_refusal():
    """Do not invent an extent for an output-only symbolic dimension."""
    raw = image_contract().model_dump(mode="json")
    raw["output"]["axes"][1] = {"dimension": {"symbolic": "K"}}
    model = SyntheticPredictionModel(ModelIOContract.model_validate(raw))
    with pytest.raises(PseudoEvidenceUnsupported, match="Cannot resolve output dimension"):
        model(torch.zeros(1, 3))


@pytest.mark.parametrize("dtype", ["uint8", "bool"])
def test_unsigned_categorical_outputs_preserve_the_winning_class(dtype):
    """Negative off-values wrap or become True and destroy the intended winner."""
    raw = image_contract().model_dump(mode="json")
    raw["output"]["dtype"] = {"admissible": [dtype]}
    model = SyntheticPredictionModel(ModelIOContract.model_validate(raw))
    assert model(torch.zeros(1, 3)).to(torch.int64).argmax(dim=1).tolist() == [0]
    assert model(torch.zeros(1, 3)).to(torch.int64).argmax(dim=1).tolist() == [1]


def test_continuous_outputs_are_bounded_and_advance_without_labels():
    raw = image_contract().model_dump(mode="json")
    raw["output"]["axes"][1] = {"dimension": {"fixed": 1}}
    model = SyntheticPredictionModel(ModelIOContract.model_validate(raw))
    first = model(torch.zeros(1, 3))
    second = model(torch.zeros(1, 3))
    assert first.tolist() == [[-1.0]]
    assert second.tolist() == [[-127 / 128]]
    raw["output"]["dtype"] = {"admissible": ["uint8"]}
    with pytest.raises(PseudoEvidenceUnsupported, match="floating dtype"):
        SyntheticPredictionModel(ModelIOContract.model_validate(raw))(torch.zeros(1, 3))
