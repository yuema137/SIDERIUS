"""Explicit composition child; never imported by the declaration preview."""

from __future__ import annotations

import argparse
import hashlib
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from core.durable_io import publish_bytes_write_once
from tools.setup_review.composition_models import (
    CHILD_RESULT_NAME,
    CompositionJob,
    CompositionResult,
    PluginObservation,
    TaskCompositionSummary,
)

if TYPE_CHECKING:
    from workflows.task_composition import RunTaskComposition


def project_composition(composition: RunTaskComposition) -> TaskCompositionSummary:
    """Project existing public facts without traversing implementation objects."""
    return TaskCompositionSummary(
        semantic_fingerprint=composition.semantic_fingerprint,
        task_data_path_id=composition.task_data_path_id,
        task_config=composition.task_config_values(),
        dataset_profile=composition.dataset_profile.model_dump(mode="json"),
        primary_metric=composition.metric.spec.model_dump(mode="json"),
        secondary_metrics=[
            metric.spec.model_dump(mode="json") for metric in composition.secondary_metrics
        ],
        parameter_rules=composition.parameter_rules.model_dump(mode="json"),
        inference_preflight=composition.inference_preflight.model_dump(mode="json"),
        source_paths=dict(composition.provenance.source_paths),
        plugins=[
            PluginObservation(identity=plugin.canonical_identity(), path=plugin.absolute_path)
            for plugin in composition.provenance.plugins
        ],
        code_package_identity=composition.code_package.identity.model_dump(mode="json")
        if composition.code_package is not None
        else None,
        prompt_renderer_identity=composition.prompt_renderer_identity.model_dump(mode="json")
        if composition.prompt_renderer_identity is not None
        else None,
        preflight_estimator_identity=composition.preflight_estimator_identity.model_dump(
            mode="json"
        ),
        data_analysis_identity=composition.data_analysis.canonical_identity()
        if composition.data_analysis is not None
        else None,
        task_health_declaration=(
            str(composition.task_health_binding.value)
            if isinstance(composition.task_health_binding, Enum)
            else str(composition.task_health_binding)
        ),
    )


def compose_in_child(job: CompositionJob) -> CompositionResult:
    """Use the launch bootstrap order before any task/registry/provider imports."""
    from core.generated_library import bind_generated_library_to_workspace

    bind_generated_library_to_workspace(job.scratch)
    from core.local_code import bind_code_package, root_code_scope

    with root_code_scope():
        try:
            from workflows.task_composition import compose_run_task_bindings

            if hashlib.sha256(Path(job.manifest).read_bytes()).hexdigest() != job.manifest_sha256:
                return CompositionResult.failed(
                    job,
                    "stale_manifest",
                    ValueError("Selected manifest changed before composition"),
                )
            composition = compose_run_task_bindings(job.manifest)
            with bind_code_package(composition.code_package):
                task = project_composition(composition)
        except Exception as error:
            return CompositionResult.failed(job, "composition", error)
        try:
            from agent.planner_strategy import resolve_planner_strategy

            identity = resolve_planner_strategy(job.planner_strategy).identity.model_dump(
                mode="json"
            )
        except Exception as error:
            return CompositionResult.failed(job, "planner_strategy", error, task=task)
        settings = None
        if job.task_settings is not None:
            try:
                from tools.setup_review.task_settings_child import resolve_task_settings

                with bind_code_package(composition.code_package):
                    settings = resolve_task_settings(job.task_settings, composition, job.scratch)
            except Exception as error:
                return CompositionResult.failed(job, "task_settings", error, task=task)
        return CompositionResult(
            request_sha256=job.digest,
            manifest_sha256=job.manifest_sha256,
            outcome="passed",
            task=task,
            planner_strategy_identity=identity,
            task_settings=settings,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args(argv)
    job = CompositionJob.model_validate_json(args.request.read_bytes())
    result = compose_in_child(job)
    publish_bytes_write_once(
        str(Path(job.scratch) / CHILD_RESULT_NAME), (result.model_dump_json() + "\n").encode()
    )
    # This is transport success, not check success; the parent reads outcome.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
