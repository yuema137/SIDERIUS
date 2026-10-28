"""The custom adaptor manifest (`siderius.adaptor-manifest/v1`) and its loading.

Loading validates the manifest, then captures the declared Python members once
through `core.local_code`; no member is executed here. The captured package
identity is the adaptor identity; the manifest digest is recorded beside it.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from core.canonical_json import canonical_sha256
from core.local_code import (
    CapturedCodePackage,
    CodePackageDeclaration,
    LocalCodeError,
    capture_package,
)
from workflows.custom_adaptors.contracts import READABLE_CONTRACTS
from workflows.custom_adaptors.errors import CustomAdaptorError
from workflows.definition.adaptor_strategies import MAX_ADAPTOR_OUTPUTS
from workflows.definition.catalog import CUSTOM_EMITTABLE

AdaptorId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]{2,99}$")]
PortName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
SymbolRef = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9_./-]+\.py:[A-Za-z_][A-Za-z0-9_]*$")
]
RelativeFile = Annotated[str, StringConstraints(min_length=1, max_length=255)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InputPortSpec(_Model):
    name: PortName
    contract: str
    cardinality: Literal["one", "many"]
    min_items: Annotated[int, Field(ge=0)] = 1
    max_items: Annotated[int, Field(gt=0)] | None = None

    @model_validator(mode="after")
    def bounded(self) -> InputPortSpec:
        if self.contract not in READABLE_CONTRACTS:
            raise ValueError(
                f"input contract {self.contract!r} is not readable by custom adaptors; "
                f"use one of {sorted(READABLE_CONTRACTS)}"
            )
        if self.cardinality == "one" and (self.min_items != 1 or self.max_items not in (None, 1)):
            raise ValueError(f"port {self.name!r}: cardinality 'one' means exactly one item")
        if self.max_items is not None and self.min_items > self.max_items:
            raise ValueError(f"port {self.name!r}: min_items exceeds max_items")
        return self

    @property
    def upper_bound(self) -> int | None:
        return 1 if self.cardinality == "one" else self.max_items


class OutputSpec(_Model):
    contract: str
    count: Annotated[int, Field(ge=1, le=MAX_ADAPTOR_OUTPUTS)] = 1


class AdaptorLimits(_Model):
    timeout_seconds: Annotated[float, Field(gt=0, le=3600, allow_inf_nan=False)]
    max_input_bytes: Annotated[int, Field(gt=0, le=256 * 1024 * 1024)]
    max_output_bytes: Annotated[int, Field(gt=0, le=64 * 1024 * 1024)]


class FixtureSpec(_Model):
    input: RelativeFile
    expected: RelativeFile


def _member(symbol: str) -> str:
    return symbol.split(":", 1)[0]


class AdaptorManifest(_Model):
    """Author-declared custom adaptor; every field is checked before any effect.

    v1 admits deterministic adaptors only (operator decision B6-D7): ``llm``
    must be absent. ``network="none"`` is the author's declaration; v1 does not
    enforce it (the child runs as the operator's user, without network or
    filesystem isolation). A ``combine`` adaptor emits a
    ``CUSTOM_EMITTABLE`` contract (B6-D3 = B). ``select`` and ``distribute``
    return indices into their single input port and never author values.
    """

    schema_version: Literal["siderius.adaptor-manifest/v1"]
    id: AdaptorId
    version: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    role: Literal["combine", "select", "distribute"]
    inputs: tuple[InputPortSpec, ...] = Field(min_length=1)
    output: OutputSpec
    entry: SymbolRef
    members: tuple[str, ...] = Field(min_length=1)
    parameters_model: SymbolRef | None = None
    deterministic: Literal[True]
    llm: None = None
    network: Literal["none"] = "none"
    limits: AdaptorLimits
    fixtures: tuple[FixtureSpec, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def consistent(self) -> AdaptorManifest:
        names = [port.name for port in self.inputs]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate input port names: {names}")
        declaration = CodePackageDeclaration(root=".", files=self.members)
        for symbol in (self.entry, self.parameters_model):
            if symbol is not None and _member(symbol) not in declaration.files:
                raise ValueError(f"{symbol!r} names a member not listed in members")
        if self.role == "combine":
            if self.output.contract not in CUSTOM_EMITTABLE:
                raise ValueError(
                    f"output contract {self.output.contract!r} is not emittable by a custom "
                    "combine: metric/score, Health, validity, identity and storage authority "
                    f"stay with the framework; emittable: {sorted(CUSTOM_EMITTABLE)}"
                )
        else:
            if len(self.inputs) != 1:
                raise ValueError(f"role {self.role!r} requires exactly one input port")
            if self.output.contract != self.inputs[0].contract:
                raise ValueError(
                    f"role {self.role!r} returns indices; output contract must equal "
                    f"input contract {self.inputs[0].contract!r}"
                )
        return self

    @property
    def entry_member(self) -> str:
        return _member(self.entry)

    @property
    def digest(self) -> str:
        return canonical_sha256(self)


class LoadedAdaptor(BaseModel):
    """A validated manifest plus its captured, unexecuted code package."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)
    manifest: AdaptorManifest
    path: Path
    package: CapturedCodePackage

    @property
    def directory(self) -> Path:
        return self.path.parent

    @property
    def identity_sha256(self) -> str:
        return self.package.identity.digest

    @property
    def source_label(self) -> str:
        """Provenance stamped into protected source fields of emitted values."""
        return f"adaptor:{self.manifest.id}@{self.identity_sha256[:12]}"

    def relative_file(self, relative: str) -> Path:
        """Resolve a manifest-relative file that must stay inside the adaptor directory."""
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts:
            raise CustomAdaptorError(
                "fixture_invalid", f"{relative!r}: use a path relative to the manifest directory"
            )
        resolved = (self.directory / path).resolve()
        if not resolved.is_relative_to(self.directory):
            raise CustomAdaptorError("fixture_invalid", f"{relative!r} escapes {self.directory}")
        return resolved


def load_adaptor(manifest_path: str | Path) -> LoadedAdaptor:
    """Validate the manifest and capture its members; executes no adaptor code."""
    path = Path(manifest_path).resolve()
    try:
        manifest = AdaptorManifest.model_validate(json.loads(path.read_bytes()))
    except OSError as exc:
        raise CustomAdaptorError("manifest_invalid", f"cannot read {path}: {exc}") from exc
    except (ValidationError, ValueError) as exc:
        raise CustomAdaptorError("manifest_invalid", f"{path}: {exc}") from exc
    try:
        package = capture_package(
            CodePackageDeclaration(root=".", files=manifest.members), path.parent
        )
    except LocalCodeError as exc:
        raise CustomAdaptorError("package_unreadable", str(exc)) from exc
    return LoadedAdaptor(manifest=manifest, path=path, package=package)
