"""Finite native-chain declarations and observations; no scientific defaults."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, model_validator

from core.generated_artifact_name import validate_generated_artifact_name
from core.seeding import RunSeed
from tools.setup_review.composition_models import TaskCheckSettings
from tools.setup_review.environment_models import EnvironmentPreviewReport
from workflows.reviewed_launch_binding import BindingModel, Digest, InputFilePin

PositiveInt = Annotated[int, Field(gt=0, strict=True)]


def canonical_path(value: Path) -> Path:
    if not value.is_absolute() or "\0" in str(value) or value != value.resolve():
        raise ValueError("noncanonical_path")
    return value


def clean_text(value: str) -> str:
    if "\0" in value:
        raise ValueError("nul_in_text")
    return value


CanonicalPath = Annotated[Path, AfterValidator(canonical_path)]
Text = Annotated[str, AfterValidator(clean_text)]
# Control aliases are rejected even if the ordinary parser would reject them.
PROTECTED = frozenset(
    [
        "mode",
        "workspace",
        "run_name",
        "num_iterations",
        "start_iter",
        "start_iteration",
        "auto_resume",
        "no_auto_resume",
        "force_fresh",
        "seed_paths",
        "source_paths",
        "run_seed",
        "dry_run",
        "validation_fixed_candidate_plan",
        "fixed_candidate_plan",
        "partition",
        "time",
        "mem",
        "gpus",
        "cpus",
        "expected_chain_capture",
        "expected_chain_capture_sha256",
        "chain_capture_input_max_bytes",
        "chain_export_fd",
        "chain_export_iteration",
    ]
)


class NativeChainRunBinding(BindingModel):
    workspace: CanonicalPath
    run_name: Text
    final_iteration: PositiveInt
    #: The operator's explicit run seed (issue #983). Absent means the first
    #: iteration's startup generates one and locks it; omitted from the
    #: serialized declaration when absent, so seedless digests are unchanged.
    run_seed: RunSeed | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def meaningful_name(self):
        validate_generated_artifact_name(self.run_name, field="run_name")
        if not self.run_name.strip():
            raise ValueError("blank_run_name")
        return self


class NativeChainDeclaration(BindingModel):
    schema_version: Literal["siderius.native-chain/v1"] = "siderius.native-chain/v1"
    recipe: Literal["native-standard-chain/v1"] = "native-standard-chain/v1"
    working_directory: CanonicalPath
    run: NativeChainRunBinding
    chain_args: tuple[Text, ...]

    @model_validator(mode="after")
    def protected_controls(self):
        for token in self.chain_args:
            name = token.split("=", 1)[0].lstrip("-").replace("-", "_")
            if token.startswith("-") and (name in PROTECTED or name.startswith("chain_")):
                raise ValueError("protected_chain_control")
        return self

    def shell_arguments(self, *, start_iteration: int = 1) -> tuple[str, ...]:
        if not 1 <= start_iteration <= self.run.final_iteration:
            raise ValueError("invalid_start_iteration")
        return (
            "--mode",
            "lilab",
            "--workspace",
            str(self.run.workspace),
            "--run_name",
            self.run.run_name,
            "--num_iterations",
            str(self.run.final_iteration),
            "--start_iter",
            str(start_iteration),
            "--no_auto_resume",
            *(() if self.run.run_seed is None else ("--run_seed", str(self.run.run_seed))),
            *self.chain_args,
        )


class NativeChainReviewRequest(BindingModel):
    source: CanonicalPath
    output: CanonicalPath
    read_only: tuple[CanonicalPath, ...]
    task_check: TaskCheckSettings
    input_max_bytes: PositiveInt


class CapturedInputFile(BindingModel):
    pin: InputFilePin
    content_base64: Text

    @model_validator(mode="after")
    def verify_bytes(self):
        data = base64.b64decode(self.content_base64, validate=True)
        if len(data) != self.pin.size or hashlib.sha256(data).hexdigest() != self.pin.sha256:
            raise ValueError("captured_input_mismatch")
        canonical_path(Path(self.pin.path))
        return self


class NativeChainCapture(BindingModel):
    schema_version: Literal["siderius.native-chain-capture/v1"] = "siderius.native-chain-capture/v1"
    declaration: NativeChainDeclaration
    source_text: Text
    source_path: CanonicalPath
    source_sha256: Digest
    declaration_sha256: Digest
    shell_argv: tuple[Text, ...]
    iteration_one_argv: tuple[Text, ...]
    environment: EnvironmentPreviewReport
    input_files: tuple[CapturedInputFile, ...]

    @model_validator(mode="after")
    def consistent_observations(self):
        declaration = self.declaration
        environment = self.environment
        binding = environment.launch_binding
        saved = environment.saved_task_check
        current = environment.current_declaration
        if (
            hashlib.sha256(self.source_text.encode()).hexdigest() != self.source_sha256
            or NativeChainDeclaration.model_validate_json(self.source_text) != declaration
            or hashlib.sha256(declaration.model_dump_json().encode()).hexdigest()
            != self.declaration_sha256
            or self.shell_argv != declaration.shell_arguments()
            or binding is None
            or saved.result.outcome != "passed"
            or saved.result.task is None
            or saved.result.task_settings is None
            or saved.result.planner_strategy_identity is None
            or tuple(current.request.argv) != self.iteration_one_argv
            or current.request != saved.declaration.request
            or current.workspace != str(declaration.run.workspace)
            or current.request.working_directory != str(declaration.working_directory)
            or binding.installation.source_root != str(declaration.working_directory)
            or tuple(item.pin for item in self.input_files) != binding.files
        ):
            raise ValueError("capture_observation_mismatch")
        values = {row.name: row.declared_value for row in current.parameters}
        if (
            values.get("run_name") != declaration.run.run_name
            or values.get("start_iteration") != 1
            or values.get("run_seed") != declaration.run.run_seed
        ):
            raise ValueError("capture_run_mismatch")
        return self


class NativeChainCaptureReference(BindingModel):
    path: CanonicalPath
    sha256: Digest
    input_max_bytes: PositiveInt


class NativeChainDispatch(BindingModel):
    capture: NativeChainCaptureReference
    iteration: PositiveInt
    argv: tuple[Text, ...]


class NativeChainRefusal(ValueError):
    """Public bounded reason, without configuration values."""
