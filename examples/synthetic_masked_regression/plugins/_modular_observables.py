"""A local-source static diagnostic; it never changes candidate selection."""

from torch import nn

from execute_tools.observables import StaticObservable

from ._modular_shared import trainable_parameters


class TrainableParameters(StaticObservable):
    def compute(self, model: nn.Module) -> float:
        return trainable_parameters(model)
