"""Data-free semantic pair and numerical custom-loss validation."""

from pathlib import Path

import torch

from agent.schemas.custom_loss_contract import ExplicitPairApplicability
from agent.schemas.custom_loss_validation import validate_custom_loss_plugin
from agent.schemas.model_io_contract import Dimension, ModelIOContract, TensorAxis, TensorContract
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


def _masked_loss_source(marker: Path | None = None) -> str:
    marker_effect = "" if marker is None else f"Path({str(marker)!r}).write_text('imported')\n"
    return (
        "from pathlib import Path\n"
        "import torch\n"
        "from pydantic import BaseModel\n"
        f"{marker_effect}"
        "class Config(BaseModel):\n    pass\n"
        "class MaskedLoss(torch.nn.Module):\n"
        "    def __init__(self, config):\n        super().__init__()\n"
        "    def forward(self, prediction, target):\n"
        "        mask = target[:, 1] > 0.5\n"
        "        return ((prediction[:, 0] - target[:, 0]) ** 2)[mask].mean()\n"
        "PLUGIN_LOSS_TYPE = 'masked'\n"
        "PLUGIN_LOSS_CONFIG_CLASS = Config\n"
        "PLUGIN_LOSS_CLASS = MaskedLoss\n"
    )


def _mse_loss_source() -> str:
    return (
        "import torch\n"
        "from pydantic import BaseModel\n"
        "class Config(BaseModel):\n    pass\n"
        "class MSELoss(torch.nn.Module):\n"
        "    def __init__(self, config):\n        super().__init__()\n"
        "    def forward(self, prediction, target):\n"
        "        return ((prediction - target) ** 2).mean()\n"
        "PLUGIN_LOSS_TYPE = 'mse'\n"
        "PLUGIN_LOSS_CONFIG_CLASS = Config\n"
        "PLUGIN_LOSS_CLASS = MSELoss\n"
    )


def _declared_pair():
    prediction = _tensor("B", 1)
    target = _tensor("B", 2)
    model_io = ModelIOContract(input=_tensor("B", 4), output=prediction)
    applicability = ExplicitPairApplicability(prediction=prediction, target=target)
    return model_io, target, applicability


def test_task_owned_masked_pair_passes_finite_backward():
    model_io, target, applicability = _declared_pair()

    error = validate_custom_loss_plugin(
        _masked_loss_source(),
        "masked",
        model_io,
        target,
        applicability,
        pair_provider=lambda: (
            torch.tensor([[0.2], [0.8]]),
            torch.tensor([[0.0, 1.0], [1.0, 1.0]]),
        ),
    )

    assert error is None


def test_bad_task_pair_refuses_before_generated_source_import(tmp_path):
    model_io, target, applicability = _declared_pair()
    marker = tmp_path / "imported"

    error = validate_custom_loss_plugin(
        _masked_loss_source(marker),
        "masked",
        model_io,
        target,
        applicability,
        pair_provider=lambda: (torch.zeros(2, 3), torch.zeros(2, 2)),
    )

    assert error is not None and "synthetic prediction axis 1" in error
    assert not marker.exists()


def test_missing_provider_for_unrealizable_pair_is_named_before_import(tmp_path):
    model_io, target, applicability = _declared_pair()
    marker = tmp_path / "imported"

    error = validate_custom_loss_plugin(
        _masked_loss_source(marker),
        "masked",
        model_io,
        target,
        applicability,
    )

    assert error is not None and "task-owned provider required" in error
    assert not marker.exists()


def test_provider_dtype_and_total_size_refuse_before_import(tmp_path):
    model_io, target, applicability = _declared_pair()
    marker = tmp_path / "imported"

    dtype_error = validate_custom_loss_plugin(
        _masked_loss_source(marker),
        "masked",
        model_io,
        target,
        applicability,
        pair_provider=lambda: (
            torch.zeros(2, 1, dtype=torch.int64),
            torch.zeros(2, 2),
        ),
    )
    size_error = validate_custom_loss_plugin(
        _masked_loss_source(marker),
        "masked",
        model_io,
        target,
        applicability,
        pair_provider=lambda: (torch.zeros(400_000, 1), torch.zeros(400_000, 2)),
    )

    assert dtype_error is not None and "dtype" in dtype_error
    assert size_error is not None and "total limit" in size_error
    assert not marker.exists()


def test_pair_must_satisfy_the_loss_applicability_dtype_before_import(tmp_path):
    broad_dtype = DtypeAdmissibility(admissible=("float32", "float64"))
    prediction = _tensor("B", 1).model_copy(update={"dtype": broad_dtype})
    target = _tensor("B", 1).model_copy(update={"dtype": broad_dtype})
    model_io = ModelIOContract(input=_tensor("B", 4), output=prediction)
    applicability = ExplicitPairApplicability(
        prediction=_tensor("B", 1, dtype="float64"),
        target=_tensor("B", 1, dtype="float64"),
    )
    marker = tmp_path / "imported"

    error = validate_custom_loss_plugin(
        _masked_loss_source(marker),
        "masked",
        model_io,
        target,
        applicability,
        pair_provider=lambda: (torch.zeros(2, 1), torch.zeros(2, 1)),
    )

    assert error is not None and "applicability prediction dtype" in error
    assert not marker.exists()


def test_equal_shape_generic_pair_remains_available_without_provider():
    from agent.schemas.custom_loss_contract import EqualShapeApplicability

    tensor = _tensor("B", "T")
    model_io = ModelIOContract(input=_tensor("B", 4), output=tensor)
    applicability = EqualShapeApplicability(
        dtype=DtypeAdmissibility(admissible=("float32",)),
        rank=2,
    )

    assert (
        validate_custom_loss_plugin(
            _mse_loss_source(),
            "mse",
            model_io,
            tensor,
            applicability,
        )
        is None
    )


def test_empty_mask_reaches_numerical_check_and_refuses_nonfinite():
    model_io, target, applicability = _declared_pair()

    error = validate_custom_loss_plugin(
        _masked_loss_source(),
        "masked",
        model_io,
        target,
        applicability,
        pair_provider=lambda: (torch.zeros(2, 1), torch.zeros(2, 2)),
    )

    assert error is not None and "non-finite scalar" in error


def test_provider_exception_is_named_before_plugin_import(tmp_path):
    model_io, target, applicability = _declared_pair()
    marker = tmp_path / "imported"

    def broken_provider():
        raise RuntimeError("synthetic fixture unavailable")

    error = validate_custom_loss_plugin(
        _masked_loss_source(marker),
        "masked",
        model_io,
        target,
        applicability,
        pair_provider=broken_provider,
    )

    assert error is not None and "provider refused" in error
    assert "RuntimeError: synthetic fixture unavailable" in error
    assert not marker.exists()


def test_concrete_parameters_are_used_instead_of_defaults():
    source = (
        _mse_loss_source()
        .replace(
            "class Config(BaseModel):\n    pass",
            "class Config(BaseModel):\n    denominator: float = 1.0",
        )
        .replace("super().__init__()", "super().__init__(); self.denominator = config.denominator")
        .replace(
            "((prediction - target) ** 2).mean()",
            "((prediction - target) ** 2).mean() / self.denominator",
        )
    )
    def pair():
        return torch.zeros(2, 1), torch.ones(2, 1)

    assert validate_custom_loss_plugin(source, "mse", pair_provider=pair) is None
    error = validate_custom_loss_plugin(
        source, "mse", pair_provider=pair, loss_parameters={"denominator": 0.0}
    )
    assert error is not None and "non-finite scalar" in error


def test_invalid_concrete_parameters_do_not_fall_back_to_defaults():
    source = _mse_loss_source().replace(
        "class Config(BaseModel):\n    pass",
        "class Config(BaseModel):\n    denominator: float = 1.0",
    )
    error = validate_custom_loss_plugin(
        source,
        "mse",
        pair_provider=lambda: (torch.zeros(2, 1), torch.ones(2, 1)),
        loss_parameters={"denominator": "not-a-number"},
    )
    assert error is not None and "supplied parameters" in error
