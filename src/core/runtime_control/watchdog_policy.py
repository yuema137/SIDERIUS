"""Explicit deadline selection, independent of runtime admission and estimation."""

from typing import Literal

RuntimeWatchdogDeadlinePolicy = Literal["budget-ceiling-v1", "forecast-tightening-v1"]
