"""Escaped human task-check summary, separate from the inert settings page."""

import html
import json

from tools.setup_review.composition_models import TaskCheckReport


def _json(value: object) -> str:
    return html.escape(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False))


def _section(title: str, explanation: str, values: dict) -> str:
    rows = "".join(
        f"<tr><th>{html.escape(str(name))}</th><td><pre>{_json(value)}</pre></td></tr>"
        for name, value in values.items()
    )
    return f"<h3>{html.escape(title)}</h3><p>{html.escape(explanation)}</p>" + (
        f"<table>{rows}</table>" if rows else "<p>No entries are declared.</p>"
    )


def render_task_check(report: TaskCheckReport) -> str:
    result = report.result
    outcome = (
        "Task and planner provider composed"
        if result.outcome == "passed"
        else "Task check did not pass"
    )
    failure = ""
    if result.failure is not None:
        failure = (
            f"<h2>Failure: {html.escape(result.failure.stage)}</h2>"
            f"<p>{html.escape(result.failure.exception_type)}</p>"
            f"<pre>{html.escape(result.failure.message)}</pre>"
        )
    task = "<p>No completed task summary is available.</p>"
    if result.task is not None:
        facts = result.task
        task = (
            "<p>These facts were projected from workflows.task_composition.RunTaskComposition. "
            "They describe the loaded declaration and captured source identities. "
            "Dataset contents, model behavior and Health execution were not tested.</p>"
            + _section(
                "Task and forward contract",
                "The task's description and declared model input/output contract.",
                {"task_data_path_id": facts.task_data_path_id, **facts.task_config},
            )
            + _section(
                "Primary metric",
                "This metric determines the reported score. Direction states whether higher or lower is better.",
                facts.primary_metric,
            )
            + _section(
                "Secondary metrics",
                "These additional observations do not replace the primary score.",
                {str(index + 1): metric for index, metric in enumerate(facts.secondary_metrics)},
            )
            + _section(
                "Dataset profile",
                "Declared partition count and task-owned format settings; no dataset contents were read or validated by the checker.",
                facts.dataset_profile,
            )
            + _section(
                "Parameter rules",
                "The composition owner's rules for which experiment parameters may change. An empty declaration adds no task-owned restrictions.",
                facts.parameter_rules,
            )
            + _section(
                "Inference preflight policy",
                "Current values resolved by the composition owner; this check did not measure inference time or memory.",
                facts.inference_preflight,
            )
            + _section(
                "Task-owned Health declaration",
                "The task's Health binding only. The effective Health roster and execution checks remain unresolved.",
                {"declaration": facts.task_health_declaration},
            )
            + "<details><summary>Technical source identities and complete task snapshot</summary>"
            + f"<pre>{_json(facts.model_dump(mode='json'))}</pre></details>"
        )
    execution = (
        _json(report.execution.model_dump(mode="json"))
        if report.execution is not None
        else "Sandbox execution did not start."
    )
    limits = "".join(f"<li>{html.escape(item)}</li>" for item in report.limitations)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SIDERIUS task composition check</title>
<style>body {{font:16px/1.5 system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem}}
pre {{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f6f8;padding:1rem}}
table {{border-collapse:collapse;width:100%;table-layout:fixed}} th,td {{border:1px solid #ccc;text-align:left;vertical-align:top;padding:.5rem;overflow-wrap:anywhere}} th {{width:30%}}
.notice {{background:#fff2cc;padding:1rem}}</style></head><body>
<h1>{html.escape(outcome)}</h1>
<p class="notice">This explicit check executed selected task/provider factories in a sandbox.
It did not run an experiment, validate dataset contents, authenticate an API key or prove launch readiness.
It does not approve or block an ordinary launch.</p>
<p>Open <a href="settings.html">the saved settings preview</a> for CLI defaults, static model routes,
the original arguments and the command to run separately. That page describes declaration inspection;
this page records the additional task-code check. Recheck after changing inputs.</p>
<dl><dt>Selected manifest</dt><dd><pre>{html.escape(report.job.manifest)}</pre></dd>
<dt>Actual future run workspace (not created by this check)</dt><dd><pre>{html.escape(report.declaration.workspace)}</pre></dd>
<dt>Check scratch directory</dt><dd><pre>{html.escape(str(report.request.scratch))}</pre></dd>
<dt>Check limits</dt><dd><pre>{_json(report.request.settings.model_dump(mode="json"))}</pre></dd></dl>
{failure}
<h2>Composed task facts</h2>{task}
<h2>Planner strategy identity</h2><pre>{_json(result.planner_strategy_identity)}</pre>
<h2>Sandbox execution</h2><pre>{execution}</pre>
<p>The runner reports status, return code and elapsed time. This is not an independently
measured orphan-free cleanup receipt or an immutable snapshot of the host.</p>
<h2>What remains unchecked</h2><ul>{limits}</ul>
<p>Keep the task/configuration inputs unchanged while checking. Scratch files are diagnostic artifacts,
not scientific run results; inspect them before removing the scratch directory yourself.</p>
</body></html>
"""
