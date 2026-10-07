"""Read standard declarations through their existing, non-executing owners."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import asdict
from pathlib import Path

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter

from core.layout import checkout_root, package_root
from tools.setup_review.environment import credential_name_checks
from tools.setup_review.models import (
    ParameterDeclaration,
    SetupDeclarationReport,
    SetupReviewRequest,
)
from tools.setup_review.routes import standard_llm_routes
from workflows.launch_identity import resolve_launch_identity
from workflows.llm_config import resolve_standard_llm_config
from workflows.standard_cli import build_parser, normalize_args

_JSON_VALUE = TypeAdapter(JsonValue, config=ConfigDict(allow_inf_nan=False))
_NORMALIZED_ALIASES = {
    "iteration_legacy": "start_iteration",
    "source_paths_legacy": "seed_paths",
}
_UNRESOLVED = [
    "Task manifest contents, task plugins, code packages and their identities are not validated "
    "or imported. A regular manifest file is not proof of a runnable task.",
    "Dataset existence, readability, split integrity and task compatibility are not checked.",
    "Hardware availability, memory requirements and effective watchdog settings are not "
    "resolved. Watchdog declarations below have not been applied to a device or profile.",
    "Static LLM routes are resolved through the standard owners. They do not establish which "
    "conditional nodes execute or how often. SDK/environment-selected endpoints, authentication "
    "and installed strategy plugins remain unchecked.",
    "Task-dependent enablement and agent-selected training values remain unresolved. In "
    "particular, a null data_analysis_enabled or trial_portion is not equivalent to false or zero.",
    "This report does not enforce budgets or validate every downstream argument combination. "
    "CLI acceptance alone does not prove that a runtime option is enforced.",
    "No LLM review has been performed. This is not a recorded decision to skip such a review.",
    "The ordinary launch command does not verify this report. Changes to input files, code, "
    "environment or hardware after inspection are not detected at launch by this tool.",
]


def _json_value(value: object) -> JsonValue:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return _JSON_VALUE.validate_python(value)


def _parameter_rows(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> list[ParameterDeclaration]:
    rows = []
    # argparse exposes defaults on its Action objects; do not copy their values.
    for action in parser._actions:
        if isinstance(action, argparse._HelpAction):
            continue
        normalized_name = _NORMALIZED_ALIASES.get(action.dest, action.dest)
        rows.append(
            ParameterDeclaration(
                name=action.dest,
                flags=list(action.option_strings),
                required=action.required,
                description=action.help or "No additional help is declared by the CLI.",
                cli_default=_json_value(action.default),
                normalized_name=normalized_name,
                declared_value=_json_value(getattr(args, normalized_name)),
                owner="standard_cli.build_parser",
            )
        )
    rows.append(
        ParameterDeclaration(
            name="human_advice_mindset",
            flags=[],
            required=False,
            description="Mindset advice read by the standard argument normalizer.",
            cli_default=None,
            normalized_name="human_advice_mindset",
            declared_value=_json_value(args.human_advice_mindset),
            owner="standard_cli.normalize_args",
        )
    )
    return rows


def _check_scope(args: argparse.Namespace) -> None:
    if args.start_iteration != 1:
        raise ValueError("Setup inspection supports only --start_iteration 1, without resume")
    unsupported = (
        "seed_paths",
        "auto_resume",
        "replace_iteration_manifest",
        "replacement_reason",
        "validation_fixed_candidate_plan",
        "print_resolved_launch_config",
    )
    for name in unsupported:
        if getattr(args, name):
            raise ValueError(f"--{name} is outside fresh single-iteration setup inspection")


def _check_locations(args: argparse.Namespace, output: Path) -> tuple[Path, Path, Path]:
    if not output.is_absolute():
        raise ValueError("Report output must be an absolute path to a new directory")
    if os.path.lexists(output):
        raise ValueError(f"Report output already exists; choose a new directory: {output}")
    workspace = Path(args.workspace).resolve()
    output = output.resolve()
    framework = checkout_root() or package_root()
    for name, path in (("Run workspace", workspace), ("Report output", output)):
        if path.is_relative_to(framework):
            raise ValueError(f"{name} must be outside the framework: {path}")
    if output.is_relative_to(workspace) or workspace.is_relative_to(output):
        raise ValueError("Report output and run workspace must be separate, non-nested directories")
    if workspace.exists() and (
        not workspace.is_dir() or next(workspace.iterdir(), None) is not None
    ):
        raise ValueError(f"Run workspace must be absent or an empty directory: {workspace}")
    if not output.parent.is_dir():
        raise ValueError(f"Create the report's parent directory first: {output.parent}")
    manifest = Path(args.task_composition).resolve()
    if not manifest.is_file():
        raise ValueError(f"Task composition must name an existing regular file: {manifest}")
    return workspace, manifest, output


def inspect_declaration(
    request: SetupReviewRequest, output: Path, *, check_environment: bool = False
) -> SetupDeclarationReport:
    """Inspect in the caller's cwd, without changing cwd or initializing execution.

    Every call parses a fresh Namespace so advice/identity caches cannot outlive
    the inspection. Relative paths retain the standard owners' existing rules.
    """
    if Path(request.working_directory).resolve() != Path.cwd():
        raise ValueError("Run the inspector from the request's working_directory")
    parser = build_parser()
    try:
        args = normalize_args(parser.parse_args(request.argv))
    except SystemExit as exc:
        raise ValueError(
            "Standard arguments did not produce a run declaration; correct the parser error "
            "above and omit --help from the saved argv"
        ) from exc
    _check_scope(args)
    workspace, manifest, output = _check_locations(args, output)
    identity = resolve_launch_identity(args)
    llm_config = resolve_standard_llm_config(args)
    routes = standard_llm_routes(
        llm_config,
        literature_enabled=identity.lit_review_enabled,
        analysis_enabled=identity.data_analysis_enabled,
        pseudo_llm=args.is_pseudo_llm,
    )
    return SetupDeclarationReport(
        request=request,
        # Resolving this symlink would silently replace a venv interpreter with
        # its base interpreter and could launch against a different installation.
        launch_argv=[sys.executable, "-m", "workflows.run_one_iteration", *request.argv],
        workspace=str(workspace),
        task_manifest=str(manifest),
        output_directory=str(output),
        parameters=_parameter_rows(parser, args),
        launch_identity=asdict(identity),
        declared_llm_config=llm_config.model_dump(mode="json", by_alias=True),
        llm_routes=routes,
        environment_check_requested=check_environment,
        credentials=credential_name_checks(routes, requested=check_environment),
        unresolved=_UNRESOLVED.copy(),
    )
