"""Run every manifest fixture twice in supervised children and compare outputs.

Deterministic adaptors (the only kind admitted in v1) must return byte-equal
canonical output on both runs, and that output must equal the fixture's
expected value after the same role validation. Expected files hold the author
form: protected fields stay unset there, because stamped provenance includes
the package identity and would change on every code edit.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.canonical_json import canonical_json_bytes
from workflows.custom_adaptors.errors import CustomAdaptorError
from workflows.custom_adaptors.manifest import FixtureSpec, LoadedAdaptor
from workflows.custom_adaptors.runner import admit_inputs, invoke, validate_output

Digest = str


class FixtureInput(BaseModel):
    """Contents of a fixture ``input`` file."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    inputs: dict[str, list[Any]]
    parameters: dict[str, Any] = Field(default_factory=dict)


class FixtureResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    input: str
    input_sha256: Digest
    expected_sha256: Digest
    output_sha256: Digest


class SelfTestReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    adaptor_id: str
    identity_sha256: Digest
    manifest_sha256: Digest
    fixtures: tuple[FixtureResult, ...]


def _read(loaded: LoadedAdaptor, relative: str) -> bytes:
    path = loaded.relative_file(relative)
    try:
        return path.read_bytes()
    except OSError as exc:
        raise CustomAdaptorError("fixture_invalid", f"cannot read {path}: {exc}") from exc


def _run_fixture(loaded: LoadedAdaptor, fixture: FixtureSpec, control: Path) -> FixtureResult:
    input_bytes = _read(loaded, fixture.input)
    expected_bytes = _read(loaded, fixture.expected)
    try:
        case = FixtureInput.model_validate_json(input_bytes)
        expected_raw = json.loads(expected_bytes)
    except (ValidationError, ValueError) as exc:
        raise CustomAdaptorError("fixture_invalid", f"{fixture.input}: {exc}") from exc
    ports = admit_inputs(loaded.manifest, case.inputs)
    first = invoke(loaded, ports, case.parameters, control / "run-1")
    second = invoke(loaded, ports, case.parameters, control / "run-2")
    if canonical_json_bytes(first) != canonical_json_bytes(second):
        raise CustomAdaptorError(
            "custom_nondeterministic", f"{fixture.input}: two runs returned different output"
        )
    output = validate_output(loaded, ports, first)
    try:
        expected = validate_output(loaded, ports, expected_raw)
    except CustomAdaptorError as exc:
        raise CustomAdaptorError("fixture_invalid", f"{fixture.expected}: {exc}") from exc
    if output.author_sha256 != expected.author_sha256:
        raise CustomAdaptorError(
            "fixture_mismatch",
            f"{fixture.input}: output {json.dumps(output.author)[:500]} differs from "
            f"{fixture.expected}",
        )
    return FixtureResult(
        input=fixture.input,
        input_sha256=hashlib.sha256(input_bytes).hexdigest(),
        expected_sha256=hashlib.sha256(expected_bytes).hexdigest(),
        output_sha256=output.author_sha256,
    )


def run_self_test(loaded: LoadedAdaptor, control_root: Path) -> SelfTestReport:
    """Every fixture must pass; the first failure raises a typed refusal."""
    results = tuple(
        _run_fixture(loaded, fixture, control_root / f"fixture-{index}")
        for index, fixture in enumerate(loaded.manifest.fixtures)
    )
    return SelfTestReport(
        adaptor_id=loaded.manifest.id,
        identity_sha256=loaded.identity_sha256,
        manifest_sha256=loaded.manifest.digest,
        fixtures=results,
    )
