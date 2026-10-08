"""Human-facing local observations with saved evidence clearly separated."""

import html
import shlex

from tools.setup_review.composition_render import _json, _section
from tools.setup_review.environment_models import EnvironmentPreviewReport
from tools.setup_review.render_routes import render_route_sections


def render_environment_preview(report: EnvironmentPreviewReport) -> str:
    declaration = report.current_declaration
    settings = report.saved_task_check.result.task_settings
    assert settings is not None  # The producer requires a successful settings check.
    task = report.saved_task_check.result.task
    assert task is not None
    command = (
        f"cd {shlex.quote(declaration.request.working_directory)} &&\n"
        f"{shlex.join(declaration.launch_argv)}"
    )
    # The credential observations are current; route enablement below comes from
    # the saved task check, whose declaration has just been compared, not rerun.
    routes = declaration.model_copy(
        update={
            "llm_routes": settings.llm_routes,
            "environment_check_requested": report.environment_check_requested,
            "credentials": report.credentials,
        }
    )
    budget_names = (
        "max_rounds",
        "trial_portion",
        "formal_portion",
        "trial_max_epochs",
        "formal_max_epochs",
        "trial_time_budget_minutes",
        "formal_time_budget_minutes",
        "trial_vram_budget_gb",
        "formal_vram_budget_gb",
        "validation_max_phase_seconds",
    )
    sections = _section(
        "Files and directories",
        "The run workspace is still empty or absent. All files from this command are in the report directory.",
        {
            "task manifest": declaration.task_manifest,
            "physical data directory": report.dataset_directory,
            "run workspace": declaration.workspace,
            "report directory": report.output,
            "saved task report": report.source_report,
        },
    )
    sections += _section(
        "Rounds, data and budgets",
        "Values come from the standard launch projection. They are declarations, not measured costs or enforcement evidence.",
        {name: report.launch_settings[name] for name in budget_names},
    )
    sections += _section(
        "Saved task settings",
        "These facts were resolved by the earlier task check. This operation did not import task code, reread plugin implementations or evaluate Health checks.",
        {
            "task": task.task_data_path_id,
            "primary metric": task.primary_metric,
            "dataset profile": task.dataset_profile,
            "selected partitions": settings.resolved_data_scope,
            "partial scope": settings.scope_is_partial,
            "analysis enabled": settings.analysis_enabled,
            "formal policy": settings.formal_policy,
            "Health enabled": settings.health_gate_enabled,
        },
    )
    sections += _section(
        "Saved Health configuration",
        "Configuration only; no Health evaluation ran.",
        settings.health_config or {},
    )
    sections += _section(
        "Hardware observed now",
        "Property discovery did not allocate a model or run a kernel. Collection errors remain explicit gaps; an available device is not a readiness certificate.",
        report.hardware.model_dump(mode="json"),
    )
    sections += _section(
        "Watchdog settings resolved now",
        "Owner: workflows.runtime_settings.resolve_watchdog_policy. Provenance identifies whether CLI values or a device profile decided these settings.",
        report.watchdog.model_dump(mode="json"),
    )
    sections += _section(
        "Complete standard launch projection",
        "Owner: workflows.standard_launch.build_standard_launch_config. Every transit field is shown, including defaults. Null can leave a downstream decision unresolved. The two formal delta fields use nan/+inf/-inf strings only to preserve permitted unused numeric declarations.",
        report.launch_settings,
    )
    limits = "".join(f"<li>{html.escape(item)}</li>" for item in report.limitations)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>SIDERIUS task and environment settings</title>
<style>body {{font:16px/1.5 system-ui; max-width:1100px; margin:2rem auto; padding:0 1rem;}}
table {{border-collapse:collapse; width:100%;}} th,td {{border:1px solid #bcc6cf;padding:.6rem;text-align:left;vertical-align:top;}}
th {{width:35%;}} pre {{white-space:pre-wrap;overflow-wrap:anywhere;}} .notice {{background:#fff2cc;padding:1rem;}}</style>
</head><body><h1>SIDERIUS task and environment settings</h1>
<p class="notice"><strong>Settings observed; launch readiness is not verified.</strong>
Saved task facts and current environment facts are shown separately. No task, training or LLM call ran in this operation.</p>
<h2>What remains unchecked</h2><ul>{limits}</ul>
{sections}
<h2>Saved task-dependent LLM routes and current optional credential-name checks</h2>
{render_route_sections(routes)}
<h2>Ordinary launch command</h2>
<p>This command can call LLM services and train models. It does not read or enforce this report; finish the outstanding checks before running it.</p>
<pre>{html.escape(command)}</pre>
<details><summary>Complete report, selected identities and historical limitations</summary><pre>{_json(report.model_dump(mode="json"))}</pre></details>
</body></html>"""
