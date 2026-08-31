"""Loss geometry is declared, not inferred from a task identity."""

import pytest

from ml_models.models_format_sandbox import validate_loss_output_geometry


@pytest.mark.parametrize("loss_type", ["focal", "focal_cw"])
def test_per_timestep_losses_require_a_temporal_axis(loss_type: str) -> None:
    with pytest.raises(ValueError, match="no temporal axis"):
        validate_loss_output_geometry(
            loss_type,
            model_type="candidate",
            output_has_temporal_axis=False,
        )


def test_declared_temporal_axis_and_undeclared_geometry_remain_legal() -> None:
    validate_loss_output_geometry("focal", model_type="candidate", output_has_temporal_axis=True)
    validate_loss_output_geometry("focal", model_type="candidate", output_has_temporal_axis=None)
