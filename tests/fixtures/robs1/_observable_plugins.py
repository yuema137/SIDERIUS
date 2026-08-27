"""Out-of-tree observable implementations, for the `R-OBS-1` composition tests.

Deliberately OUTSIDE any package the framework imports: these are loaded by
PATH through the manifest's ``file:`` envelope, which is the form that proves
a task needs no framework edit to declare an observable. The leading
underscore keeps them out of every directory scanner.
"""

from __future__ import annotations

from typing import Any

from execute_tools.observables import DynamicObservable, StaticObservable


class MeanTargetObservable(DynamicObservable):
    """Streaming mean of the target values seen in one validation pass."""

    def __init__(self) -> None:
        self._total = 0.0
        self._count = 0

    def reset(self) -> None:
        self._total = 0.0
        self._count = 0

    def update(self, output: Any, target: Any) -> None:
        self._total += float(target.sum().item())
        self._count += int(target.numel())

    def value(self) -> float:
        return self._total / self._count if self._count else 0.0


class OutputMeanObservable(DynamicObservable):
    """Streaming mean of the model's raw outputs — a second dynamic name."""

    def __init__(self) -> None:
        self._total = 0.0
        self._count = 0

    def reset(self) -> None:
        self._total = 0.0
        self._count = 0

    def update(self, output: Any, target: Any) -> None:
        self._total += float(output.sum().item())
        self._count += int(output.numel())

    def value(self) -> float:
        return self._total / self._count if self._count else 0.0


class ParameterCountObservable(StaticObservable):
    """Trainable parameter count read off the TRAINED model."""

    def compute(self, model: Any) -> float:
        return float(sum(p.numel() for p in model.parameters() if p.requires_grad))


class RaisingDynamicObservable(DynamicObservable):
    """Raises on update — the diagnostic-not-fatal path."""

    def reset(self) -> None:
        return None

    def update(self, output: Any, target: Any) -> None:
        raise RuntimeError("deliberate observable failure")

    def value(self) -> float:
        return 1.0


class NonFiniteDynamicObservable(DynamicObservable):
    """Returns a non-finite value — an absence, never a sentinel point."""

    def reset(self) -> None:
        return None

    def update(self, output: Any, target: Any) -> None:
        return None

    def value(self) -> float:
        return float("nan")


class BatchCountObservable(DynamicObservable):
    """Counts the validation ROWS fed to it in one epoch.

    Exists so a test can assert an expectation computed from the fixture's
    own geometry, independently of anything the engine reports. An observable
    that is reset and read but never FED still returns a finite, correctly
    shaped series — so only a value with an externally known answer can
    distinguish "wired up" from "wired up and actually receiving batches".
    """

    def __init__(self) -> None:
        self._rows = 0

    def reset(self) -> None:
        self._rows = 0

    def update(self, output: Any, target: Any) -> None:
        self._rows += int(target.shape[0])

    def value(self) -> float:
        return float(self._rows)


class FirstEpochOnlyObservable(DynamicObservable):
    """Produces a value in the FIRST epoch only, then fails.

    The partial-series case: the resulting series is shorter than the epoch
    axis, and the missing point is not at a known index.
    """

    def __init__(self) -> None:
        self._epochs = 0

    def reset(self) -> None:
        self._epochs += 1

    def update(self, output: Any, target: Any) -> None:
        return None

    def value(self) -> float:
        if self._epochs > 1:
            raise RuntimeError("this observable only works in the first epoch")
        return 1.0


class RaisingStaticObservable(StaticObservable):
    """Raises on compute — the static diagnostic-not-fatal path."""

    def compute(self, model: Any) -> float:
        raise RuntimeError("deliberate static observable failure")


class NotAnObservable:
    """Neither base — composition must refuse it."""


class BothKinds(DynamicObservable, StaticObservable):
    """Claims both acquisitions — composition must refuse it."""

    def reset(self) -> None:
        return None

    def update(self, output: Any, target: Any) -> None:
        return None

    def value(self) -> float:
        return 0.0

    def compute(self, model: Any) -> float:
        return 0.0
