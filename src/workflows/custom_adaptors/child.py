"""Supervised child: verify the captured package, call the adaptor, write raw output.

    python -m workflows.custom_adaptors.child <invocation.json>

The child verifies every member pin through ``bootstrap_code_package`` before
executing adaptor code, validates inputs into native models, calls the declared
function once and writes its JSON-compatible return value. The parent alone
validates that value against the manifest; this process never decides validity.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel
from pydantic_core import to_jsonable_python

from core.local_code import LocalCodeError, acquire_module, bootstrap_code_package
from workflows.custom_adaptors.contracts import validate_values
from workflows.custom_adaptors.interface import AdaptorContext, CustomInputItem
from workflows.custom_adaptors.invocation import (
    ADAPTOR_EXCEPTION_EXIT,
    IDENTITY_MISMATCH_EXIT,
    CustomInvocation,
)


def _symbol(path: str, name: str) -> Any:
    with acquire_module(path) as module:
        if module is None:
            raise LocalCodeError(f"{path} is not a member of the captured package")
        return getattr(module, name)


def _parameters(invocation: CustomInvocation) -> BaseModel | None:
    if invocation.parameters_path is None or invocation.parameters_class is None:
        return None
    model = _symbol(invocation.parameters_path, invocation.parameters_class)
    if not (isinstance(model, type) and issubclass(model, BaseModel)):
        raise TypeError(f"parameters_model {invocation.parameters_class!r} is not a Pydantic model")
    return model.model_validate(invocation.parameters)


def _invoke(invocation: CustomInvocation) -> Any:
    inputs = MappingProxyType(
        {
            port.name: tuple(
                CustomInputItem(index=index, value=value)
                for index, value in enumerate(validate_values(port.contract, port.values))
            )
            for port in invocation.ports
        }
    )
    function = _symbol(invocation.entry_path, invocation.entry_function)
    return function(inputs, _parameters(invocation), AdaptorContext(invocation.adaptor_id))


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    invocation = CustomInvocation.model_validate_json(Path(args[0]).read_bytes())
    try:
        bootstrap_code_package(invocation.transport_manifest, invocation.transport_sha256)
    except LocalCodeError as exc:
        print(f"[custom_identity_mismatch] {exc}", file=sys.stderr)
        return IDENTITY_MISMATCH_EXIT
    try:
        result = _invoke(invocation)
        payload = json.dumps(to_jsonable_python(result))
    except BaseException:  # Adaptor code may raise anything, including SystemExit.
        traceback.print_exc()
        return ADAPTOR_EXCEPTION_EXIT
    Path(invocation.output_path).write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
