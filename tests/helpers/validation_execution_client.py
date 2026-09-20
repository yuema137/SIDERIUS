"""Synthetic client for real child-binding transport tests, without data or services."""

from __future__ import annotations

import sys
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from execute_tools.validation_execution import (
    bound_validation_rows,
    child_validation_executor_binding,
)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    rows: Annotated[StrictInt, Field(gt=0)]


class Client:
    def __init__(self, settings):
        self.settings = Settings.model_validate(settings)

    def declared_rows(self, scope):
        return self.settings.rows

    def observe(self, request, callbacks):
        raise NotImplementedError("transport test does not execute validation")


def create(settings):
    return Client(settings)


if __name__ == "__main__":
    with child_validation_executor_binding(sys.argv[1]):
        print(bound_validation_rows(object()))
