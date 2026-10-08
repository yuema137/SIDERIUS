"""Project one existing parse into explicit, credential-free child inputs."""

import argparse
from pathlib import Path
from typing import cast

from tools.setup_review.models import SetupDeclarationReport
from tools.setup_review.task_settings_models import TaskSettingsInputs, encode_formal_delta
from workflows.llm_config import WorkflowLLMConfig


def project_task_settings(
    args: argparse.Namespace, report: SetupDeclarationReport, config: WorkflowLLMConfig
) -> TaskSettingsInputs:
    path = args.health_checks_config
    if path:
        path = str((Path(report.request.working_directory) / path).absolute())
    return TaskSettingsInputs(
        data_scope=args.data_scope,
        formal_strategy=args.formal_strategy,
        health_gate_enabled=args.health_gate_enabled,
        health_gate_files=args.health_gate_files,
        health_checks_config=path,
        healthgate_mode=args.healthgate_mode,
        result_authority=args.result_authority,
        enable_chain_incumbent_formal_gates=args.enable_chain_incumbent_formal_gates,
        skip_formal_min_delta=encode_formal_delta(args.skip_formal_min_delta),
        bypass_formal_time_budget_min_delta=encode_formal_delta(
            args.bypass_formal_time_budget_min_delta
        ),
        analysis_enabled=cast(bool | None, report.launch_identity["data_analysis_enabled"]),
        literature_enabled=cast(bool, report.launch_identity["lit_review_enabled"]),
        pseudo_llm=args.is_pseudo_llm,
        llm_config=config,
    )
