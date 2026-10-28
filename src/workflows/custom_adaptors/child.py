"""Supervised child: verify the captured package, call the adaptor, write raw output.

    python -P -s -m workflows.custom_adaptors.child <invocation.json>

Order: redirect stdout/stderr into a size-capped log, verify every member pin
(``bootstrap_code_package``), import the entry and parameters model from
captured bytes, validate parameters and inputs, write the ready marker, call
the function once, then write the JSON output if it fits ``max_output_bytes``.
Any failure writes a typed ``ChildFailure`` and exits 1. The parent alone
decides output validity; this process never does.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel
from pydantic_core import to_jsonable_python

from core.local_code import LocalCodeError, acquire_module, bootstrap_code_package
from workflows.custom_adaptors.contracts import validate_values
from workflows.custom_adaptors.interface import AdaptorContext, CustomInputItem
from workflows.custom_adaptors.invocation import (
    FAILURE_FILE,
    LOG_FILE,
    MAX_LOG_BYTES,
    OUTPUT_FILE,
    READY_FILE,
    ChildFailure,
    CustomInvocation,
)


class _Failure(Exception):
    def __init__(self, failure: ChildFailure):
        super().__init__(failure.detail)
        self.failure = failure


def _fail(stage: str, detail: str) -> _Failure:
    return _Failure(ChildFailure.model_validate({"stage": stage, "detail": detail[-4000:]}))


@contextmanager
def _bounded_log(path: Path, limit: int) -> Iterator[None]:
    """Route fd 1 and 2 through a pipe; keep the first ``limit`` bytes in ``path``."""
    sys.stdout.flush()
    sys.stderr.flush()
    read_fd, write_fd = os.pipe()
    saved = (os.dup(1), os.dup(2))
    os.dup2(write_fd, 1)
    os.dup2(write_fd, 2)
    os.close(write_fd)

    def drain() -> None:
        kept = 0
        with open(path, "wb") as log, os.fdopen(read_fd, "rb", buffering=0) as source:
            while chunk := source.read(65536):
                part = chunk[: max(0, limit - kept)]
                log.write(part)
                kept += len(part)

    thread = threading.Thread(target=drain, daemon=True)
    thread.start()
    try:
        yield
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(saved[0], 1)
        os.dup2(saved[1], 2)
        for fd in saved:
            os.close(fd)
        thread.join(timeout=5.0)  # Escaped descendants may keep the pipe open.


def _symbol(path: str, name: str) -> Any:
    with acquire_module(path) as module:
        if module is None:
            raise LocalCodeError(f"{path} is not a member of the captured package")
        return getattr(module, name)


def _prepare(invocation: CustomInvocation) -> tuple[Any, Any, BaseModel | None]:
    """Everything that must succeed before adaptor code runs; typed failures."""
    try:
        bootstrap_code_package(invocation.transport_manifest, invocation.transport_sha256)
    except LocalCodeError as exc:
        raise _fail("identity", str(exc)) from exc
    function = _symbol(invocation.entry_path, invocation.entry_function)
    parameters: BaseModel | None = None
    if invocation.parameters_path is not None and invocation.parameters_class is not None:
        model = _symbol(invocation.parameters_path, invocation.parameters_class)
        if not (isinstance(model, type) and issubclass(model, BaseModel)):
            raise _fail("parameters", f"{invocation.parameters_class!r} is not a Pydantic model")
        try:
            parameters = model.model_validate(invocation.parameters)
        except ValueError as exc:
            raise _fail("parameters", str(exc)) from exc
    try:
        inputs = MappingProxyType(
            {
                port.name: tuple(
                    CustomInputItem(index=index, value=value)
                    for index, value in enumerate(validate_values(port.contract, port.values))
                )
                for port in invocation.ports
            }
        )
    except ValueError as exc:
        raise _fail("input", str(exc)) from exc
    return function, inputs, parameters


def _run(invocation: CustomInvocation) -> None:
    function, inputs, parameters = _prepare(invocation)
    invocation.file(READY_FILE).write_bytes(b"")
    try:
        result = function(inputs, parameters, AdaptorContext(invocation.adaptor_id))
    except BaseException as exc:  # Adaptor code may raise anything, including SystemExit.
        raise _fail("adaptor", traceback.format_exc()) from exc
    try:
        payload = json.dumps(to_jsonable_python(result)).encode()
    except (TypeError, ValueError) as exc:
        raise _fail("output", f"return value is not JSON-compatible: {exc}") from exc
    if len(payload) > invocation.max_output_bytes:
        raise _fail(
            "output", f"output is {len(payload)} bytes; limit {invocation.max_output_bytes}"
        )
    invocation.file(OUTPUT_FILE).write_bytes(payload)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    invocation = CustomInvocation.model_validate_json(Path(args[0]).read_bytes())
    with _bounded_log(invocation.file(LOG_FILE), MAX_LOG_BYTES):
        try:
            _run(invocation)
        except _Failure as exc:
            failure = exc.failure
        except BaseException:  # Import-time adaptor errors (entry or helper modules).
            failure = _fail("adaptor", traceback.format_exc()).failure
        else:
            return 0
        print(failure.detail, file=sys.stderr)
    invocation.file(FAILURE_FILE).write_text(failure.model_dump_json(), encoding="utf-8")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
