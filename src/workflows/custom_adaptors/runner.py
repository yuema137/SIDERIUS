"""Parent side of one custom adaptor invocation: admit inputs, supervise, validate output.

Process launch and failure classification belong to ``process.py``. Inputs and
outputs travel as JSON files in a caller-owned control directory. This is
reproducibility machinery, not a security sandbox (`core/local_code/README.md`).
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, StrictInt, TypeAdapter, ValidationError

from core.canonical_json import canonical_json_bytes, canonical_sha256
from core.local_code import CodePackageDeclaration, LocalCodeError, capture_package
from core.local_code.transport import publish_transport
from workflows.custom_adaptors.contracts import dump_values, validate_values
from workflows.custom_adaptors.errors import CustomAdaptorError
from workflows.custom_adaptors.invocation import OUTPUT_FILE, CustomInvocation, PortValues
from workflows.custom_adaptors.manifest import AdaptorManifest, LoadedAdaptor
from workflows.custom_adaptors.process import launch
from workflows.custom_adaptors.protected import stamp_protected

_INDICES = TypeAdapter(list[StrictInt])
_PARTITION = TypeAdapter(list[list[StrictInt]])


class CustomOutput(BaseModel):
    """Validated output of one invocation.

    ``author`` is the canonical author form (fixture comparison, determinism);
    ``stamped`` carries framework provenance in protected fields (combine only).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
    author: list[Any]
    stamped: list[Any]

    @property
    def author_sha256(self) -> str:
        return canonical_sha256(self.author)


def admit_inputs(manifest: AdaptorManifest, inputs: Mapping[str, Any]) -> tuple[PortValues, ...]:
    """Validate port presence, cardinality and native contracts before any launch."""
    declared = {port.name for port in manifest.inputs}
    if set(inputs) != declared:
        raise CustomAdaptorError(
            "custom_invalid_input",
            f"ports {sorted(inputs)} differ from declared {sorted(declared)}",
        )
    ports: list[PortValues] = []
    for port in manifest.inputs:
        raw = inputs[port.name]
        if not isinstance(raw, list):
            raise CustomAdaptorError("custom_invalid_input", f"port {port.name!r} needs a list")
        upper = port.upper_bound
        if len(raw) < port.min_items or (upper is not None and len(raw) > upper):
            raise CustomAdaptorError(
                "custom_invalid_input",
                f"port {port.name!r} has {len(raw)} items; declared {port.min_items}..{upper}",
            )
        try:
            values = dump_values(port.contract, validate_values(port.contract, raw))
        except ValidationError as exc:
            raise CustomAdaptorError(
                "custom_invalid_input", f"port {port.name!r} ({port.contract}): {exc}"
            ) from exc
        ports.append(PortValues(name=port.name, contract=port.contract, values=values))
    return tuple(ports)


def _invalid(message: str) -> CustomAdaptorError:
    return CustomAdaptorError("custom_invalid_output", message)


def _validate_indices(raw: object, size: int, limit: int) -> list[int]:
    indices = _INDICES.validate_python(raw)
    if len(set(indices)) != len(indices) or any(not 0 <= i < size for i in indices):
        raise _invalid(f"indices {indices} must be unique and within 0..{size - 1}")
    if len(indices) > limit:
        raise _invalid(f"{len(indices)} indices exceed output count {limit}")
    return indices


def _validate_partition(raw: object, size: int, count: int) -> list[list[int]]:
    partition = _PARTITION.validate_python(raw)
    if len(partition) != count:
        raise _invalid(f"partition has {len(partition)} outputs; declared count is {count}")
    flat = [index for group in partition for index in group]
    if len(set(flat)) != len(flat) or any(not 0 <= i < size for i in flat):
        raise _invalid(f"partition {partition} must be disjoint and within 0..{size - 1}")
    return partition


def validate_output(
    loaded: LoadedAdaptor, ports: tuple[PortValues, ...], raw: object
) -> CustomOutput:
    """Apply the role's output rules; values never pass without native validation."""
    manifest = loaded.manifest
    try:
        if manifest.role == "select":
            indices = _validate_indices(raw, len(ports[0].values), manifest.output.count)
            return CustomOutput(author=list(indices), stamped=list(indices))
        if manifest.role == "distribute":
            partition = _validate_partition(raw, len(ports[0].values), manifest.output.count)
            return CustomOutput(author=list(partition), stamped=list(partition))
        contract = manifest.output.contract
        author = dump_values(contract, validate_values(contract, raw))
        if not 1 <= len(author) <= manifest.output.count:
            raise _invalid(f"{len(author)} values; declared 1..{manifest.output.count}")
        stamped = stamp_protected(contract, author, loaded.source_label)
        return CustomOutput(
            author=author, stamped=dump_values(contract, validate_values(contract, stamped))
        )
    except ValueError as exc:  # Includes Pydantic ValidationError.
        raise _invalid(str(exc)) from exc


def invoke(
    loaded: LoadedAdaptor,
    ports: tuple[PortValues, ...],
    parameters: Mapping[str, Any],
    control_dir: Path,
) -> object:
    """Run the adaptor once in a supervised child; return its parsed raw output."""
    manifest = loaded.manifest
    if manifest.parameters_model is None and parameters:
        raise CustomAdaptorError(
            "custom_invalid_input", "parameters given without parameters_model"
        )
    size = len(canonical_json_bytes([port.model_dump(mode="json") for port in ports]))
    if size > manifest.limits.max_input_bytes:
        raise CustomAdaptorError(
            "custom_invalid_input",
            f"inputs are {size} bytes; limit {manifest.limits.max_input_bytes}",
        )
    control_dir.mkdir(parents=True, exist_ok=False)
    transport, transport_digest = publish_transport(loaded.package, control_dir / "task_code")
    root = loaded.package.locator_root
    parameters_path = parameters_class = None
    if manifest.parameters_model is not None:
        member, parameters_class = manifest.parameters_model.split(":")
        parameters_path = str(root / member)
    invocation = CustomInvocation(
        adaptor_id=manifest.id,
        role=manifest.role,
        transport_manifest=str(transport),
        transport_sha256=transport_digest,
        entry_path=str(root / manifest.entry_member),
        entry_function=manifest.entry.split(":")[1],
        parameters_path=parameters_path,
        parameters_class=parameters_class,
        ports=ports,
        parameters=dict(parameters),
        control_dir=str(control_dir),
        max_output_bytes=manifest.limits.max_output_bytes,
    )
    request = control_dir / "invocation.json"
    request.write_text(invocation.model_dump_json(), encoding="utf-8")
    launch(invocation, request, manifest.limits.timeout_seconds, lambda: _pins_changed(loaded))
    return _read_output(manifest, invocation.file(OUTPUT_FILE))


def _pins_changed(loaded: LoadedAdaptor) -> bool:
    """Independent re-capture of the declared members against the loaded identity."""
    try:
        current = capture_package(
            CodePackageDeclaration(root=".", files=loaded.manifest.members), loaded.directory
        )
    except LocalCodeError:
        return True
    return current.identity != loaded.package.identity


def _read_output(manifest: AdaptorManifest, output: Path) -> object:
    try:
        size = output.stat().st_size
        if size > manifest.limits.max_output_bytes:
            raise _invalid(f"output is {size} bytes; limit {manifest.limits.max_output_bytes}")
        return json.loads(output.read_bytes())
    except (OSError, ValueError) as exc:
        raise _invalid(f"unreadable output: {exc}") from exc


def run_once(
    loaded: LoadedAdaptor,
    inputs: Mapping[str, Any],
    parameters: Mapping[str, Any],
    control_dir: Path,
) -> tuple[CustomOutput, float]:
    """Admit inputs, invoke once, validate; return the output and elapsed seconds."""
    started = time.perf_counter()
    ports = admit_inputs(loaded.manifest, inputs)
    raw = invoke(loaded, ports, parameters, control_dir)
    return validate_output(loaded, ports, raw), time.perf_counter() - started
