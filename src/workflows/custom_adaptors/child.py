"""Supervised child: verify the captured package, call the adaptor, write raw output.

    python -P -s -m workflows.custom_adaptors.child <invocation.json>

Order: redirect stdout/stderr into a size-capped log, verify every member pin
(``bootstrap_code_package``), validate inputs, create the ``entered`` marker
(``O_EXCL``) immediately before the first member import, import the entry and
parameters model from captured bytes (member module bodies run here), validate
parameters, call the function once, then write the JSON output if it fits
``max_output_bytes``. Any failure writes a typed ``ChildFailure`` hint and exits
1. The parent alone classifies failures and decides output validity.
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
    ENTERED_FILE,
    FAILURE_FILE,
    LOG_FILE,
    MAX_LOG_BYTES,
    OUTPUT_FILE,
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
    """Route fd 1 and 2 through a pipe; keep the first ``limit`` bytes in ``path``.

    The parent's stdout/stderr pipes are not duplicated or restored: after the
    ``dup2`` this process holds no descriptor to them, so adaptor code cannot
    write past the cap into the supervisor's capture. On exit fd 1 and 2 point
    at ``/dev/null``; failure details travel through the log and failure file.
    """
    sys.stdout.flush()
    sys.stderr.flush()
    read_fd, write_fd = os.pipe()
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
        null = os.open(os.devnull, os.O_WRONLY)
        os.dup2(null, 1)
        os.dup2(null, 2)
        os.close(null)
        thread.join(timeout=5.0)  # Escaped descendants may keep the pipe open.


def _symbol(path: str, name: str) -> Any:
    with acquire_module(path) as module:
        if module is None:
            raise LocalCodeError(f"{path} is not a member of the captured package")
        return getattr(module, name)


def _inputs(invocation: CustomInvocation) -> MappingProxyType[str, tuple[CustomInputItem, ...]]:
    try:
        return MappingProxyType(
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


def _parameters(invocation: CustomInvocation) -> BaseModel | None:
    if invocation.parameters_path is None or invocation.parameters_class is None:
        return None
    model = _symbol(invocation.parameters_path, invocation.parameters_class)
    if not (isinstance(model, type) and issubclass(model, BaseModel)):
        raise _fail("parameters", f"{invocation.parameters_class!r} is not a Pydantic model")
    try:
        return model.model_validate(invocation.parameters)
    except ValueError as exc:
        raise _fail("parameters", str(exc)) from exc


def _run(invocation: CustomInvocation) -> None:
    try:
        bootstrap_code_package(invocation.transport_manifest, invocation.transport_sha256)
    except LocalCodeError as exc:
        raise _fail("identity", str(exc)) from exc
    inputs = _inputs(invocation)
    # No adaptor code has run yet; from here on, member module bodies execute.
    os.close(os.open(invocation.file(ENTERED_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    function = _symbol(invocation.entry_path, invocation.entry_function)
    parameters = _parameters(invocation)
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
