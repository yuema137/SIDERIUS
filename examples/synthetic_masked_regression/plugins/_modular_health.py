"""Local check registration plus the existing task-owned relative view module."""

from typing import ClassVar

from execute_tools.health_checks import register
from execute_tools.health_checks.sample_dispersion_floor import SampleDispersionFloorCheck

from ._masked_health_views import (
    MaskedRegressionHealthViews as MaskedRegressionHealthViews,
)


class ModularDispersion(SampleDispersionFloorCheck):
    """Same estimator and threshold handling, registered through a local entry."""

    name: ClassVar[str] = "modular_prediction_dispersion"


register(ModularDispersion())
