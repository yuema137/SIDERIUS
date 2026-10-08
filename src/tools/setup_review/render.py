"""Static, escaped HTML for a local declaration snapshot."""

from __future__ import annotations

import html
import json
import shlex

from tools.setup_review.models import SetupDeclarationReport
from tools.setup_review.render_routes import render_route_sections
from tools.setup_review.task_settings_models import FORMAL_DELTA_FIELDS


def _display(value: object) -> str:
    return html.escape(json.dumps(value, ensure_ascii=False, indent=2))


def render_html(report: SetupDeclarationReport) -> str:
    """Render plain text as HTML, never as executable markup or script."""
    command = (
        f"cd {shlex.quote(report.request.working_directory)} &&\n{shlex.join(report.launch_argv)}"
    )
    rows = []
    for parameter in report.parameters:
        label = ", ".join(parameter.flags) or parameter.name
        default = (
            "No CLI flag; added during normalization"
            if parameter.owner == "standard_cli.normalize_args"
            else _display(parameter.cli_default)
        )
        value = _display(parameter.declared_value)
        if parameter.name in FORMAL_DELTA_FIELDS and isinstance(parameter.declared_value, str):
            value += " (nonfinite numeric declaration; retained only when unused by formal gates)"
        rows.append(
            f"<tr id='{html.escape(parameter.name)}'>"
            f"<th scope='row'>{html.escape(label)}"
            f"{' (required)' if parameter.required else ''}"
            f"<details><summary>CLI help</summary>{html.escape(parameter.description)}"
            "</details></th>"
            f"<td><pre>{default}</pre></td>"
            f"<td><pre>{value}</pre>"
            f"<small>{html.escape(parameter.normalized_name)}</small></td></tr>"
        )
    limitations = "".join(f"<li>{html.escape(item)}</li>" for item in report.unresolved)
    summary_names = {
        "max_rounds",
        "trial_portion",
        "train_portion",
        "eval_portion",
        "formal_portion",
        "formal_train_portion",
        "formal_eval_portion",
        "trial_max_epochs",
        "formal_max_epochs",
        "trial_time_budget_minutes",
        "formal_time_budget_minutes",
        "trial_vram_budget_gb",
        "formal_vram_budget_gb",
        "data_scope",
        "training_validation_portion",
    }
    summary = "".join(
        f"<li><a href='#{html.escape(row.name)}'>{html.escape(row.name)}</a>: "
        f"<code>{_display(row.declared_value)}</code></li>"
        for row in report.parameters
        if row.name in summary_names
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SIDERIUS run settings preview</title>
<style>
body {{font: 16px/1.5 system-ui, sans-serif; max-width: 1100px; margin: 2rem auto;
padding: 0 1rem; color: #18212b; background: #fff;}}
h1,h2 {{line-height: 1.2}} pre {{white-space: pre-wrap; overflow-wrap: anywhere;}}
table {{border-collapse: collapse; width: 100%; table-layout: fixed;}}
th,td {{border: 1px solid #bcc6cf; padding: .65rem; text-align: left;
vertical-align: top; overflow-wrap: anywhere;}} th {{width: 30%;}}
small {{color: #425569;}} .notice {{padding: 1rem; background: #fff2cc;}}
</style></head><body>
<h1>SIDERIUS run settings preview</h1>
<p class="notice"><strong>Settings read; launch readiness is not verified.</strong>
No experiment or LLM review has run. This optional report does not approve or block a launch.</p>
<h2>What this command declares</h2>
<p>One standard iteration in a fresh workspace.</p>
<dl><dt>Run workspace</dt><dd><pre>{html.escape(report.workspace)}</pre></dd>
<dt>Task manifest (contents and plugins unchecked)</dt>
<dd><pre>{html.escape(report.task_manifest)}</pre></dd>
<dt>Report directory</dt><dd><pre>{html.escape(report.output_directory)}</pre></dd></dl>
<h2>Declared rounds, data and budgets</h2>
<p>These are declarations, not measured resource requirements or proof that limits
are enforced. Follow a parameter link for its default and CLI help.</p><ul>{summary}</ul>
<h2>Command to run separately</h2>
<p>Finish the outstanding checks below before using this ordinary launch command.
It does not compare the current configuration with this report. Running it can call
LLM services and start training; this inspector has done neither.</p>
<pre>{html.escape(command)}</pre>
<h2>What remains unchecked</h2><ul>{limitations}</ul>
{render_route_sections(report)}
<h2>Settings after CLI parsing</h2>
<p>Defaults come from the standard runner's parser. The last column is the normalized
setting after parsing, aliases and advice have been applied, not a complete effective
runtime configuration. A null value is not
automatically zero or disabled. See the original arguments below for what was
explicitly written; matching a default does not prove that a flag was omitted.</p>
<table><thead><tr><th>Parameter</th><th>CLI default</th><th>Declared value</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table>
<h2>Launch identity resolved from declarations</h2>
<p>Owner: workflows.launch_identity.resolve_launch_identity. These selected identities
do not cover task implementation or all runtime inputs.</p>
<pre>{_display(report.launch_identity)}</pre>
<h2>Declared LLM configuration</h2>
<p>Owner: workflows.llm_config.resolve_standard_llm_config. This is the declaration;
the separate static-route table applies node/transport defaults. Authentication,
task enablement and SDK/environment-selected values remain unchecked.</p>
<pre>{_display(report.declared_llm_config)}</pre>
<details><summary>Original request and complete report</summary>
<pre>{_display(report.model_dump(mode="json"))}</pre></details>
</body></html>
"""
