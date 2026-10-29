"""Finite native-chain declarations and observations; no scientific defaults."""

from __future__ import annotations

import argparse
import base64
import hashlib
from contextlib import redirect_stderr
from functools import cache
from io import StringIO
from pathlib import Path
from typing import Annotated, Literal, cast

from pydantic import AfterValidator, Field, model_validator

from core.generated_artifact_name import validate_generated_artifact_name
from core.seeding import RunSeed
from tools.setup_review.composition_models import TaskCheckSettings
from tools.setup_review.environment_models import EnvironmentPreviewReport
from workflows.reviewed_launch_binding import BindingModel, Digest, InputFilePin
from workflows.standard_cli import build_parser

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


@cache
def _control_parser() -> tuple[argparse.ArgumentParser, frozenset[str]]:
    parser = build_parser()
    # Shell-only controls also belong to the declaration, not chain_args.
    for name in sorted(PROTECTED):
        if f"--{name}" not in parser._option_string_actions:
            parser.add_argument(f"--{name}")
    protected_dests = frozenset(
        action.dest
        for action in parser._actions
        if any(
            option.lstrip("-").replace("-", "_") in PROTECTED
            or option.lstrip("-").replace("-", "_").startswith("chain_")
            for option in action.option_strings
        )
    )
    return parser, protected_dests


def _resolve_option(parser: argparse.ArgumentParser, token: str) -> argparse.Action | None:
    # CPython ArgumentParser._parse_optional owns option/alias/abbreviation resolution.
    # Early 3.12 returns one tuple and raises on ambiguity; 3.12.13 returns a list.
    try:
        with redirect_stderr(StringIO()):
            result = cast(
                list[tuple[argparse.Action | None, str, str | None, str | None]]
                | tuple[argparse.Action | None, str, str | None]
                | None,
                parser._parse_optional(token),
            )
    except (SystemExit, argparse.ArgumentError) as exc:
        raise ValueError(f"ambiguous_chain_option: {token.split('=', 1)[0]}") from exc
    if result is None:
        return None
    if isinstance(result, list):
        if len(result) != 1:
            raise ValueError(f"ambiguous_chain_option: {token.split('=', 1)[0]}")
        return result[0][0]
    return result[0]


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
        parser, protected_dests = _control_parser()
        for token in self.chain_args:
            if token == "--":
                raise ValueError("chain_option_terminator: bare -- is not allowed in chain_args")
            action = _resolve_option(parser, token)
            option = token.split("=", 1)[0]
            # Preserve the declaration's normalized spelling policy for unknown options.
            if action is None and option.startswith("--"):
                normalized = "--" + option[2:].replace("-", "_")
                action = _resolve_option(parser, normalized)
            if action is not None and action.dest in protected_dests:
                raise ValueError(
                    f"protected_chain_control: {option} expands to {action.option_strings[0]}"
                )
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
