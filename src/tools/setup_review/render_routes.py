"""Human-readable static routes and optional environment checks."""

import html
import json

from tools.setup_review.models import SetupDeclarationReport


def render_route_sections(report: SetupDeclarationReport) -> str:
    rows = []
    for route in report.llm_routes:
        settings = route.transport
        if settings is None:
            detail = html.escape(route.issue or "Unresolved")
        else:
            endpoint = settings.base_url or "Unresolved: SDK/environment selects endpoint"
            attempts = (
                "unbounded" if settings.max_retries is None else str(max(1, settings.max_retries))
            )
            detail = (
                f"<strong>{html.escape(settings.provider)} / {html.escape(str(settings.model_id))}</strong>"
                f"<br>Reasoning effort: {html.escape(settings.reasoning_effort or 'unspecified')}"
                f"<br>Transient-error total attempts: {attempts} (max_retries={settings.max_retries})"
                f"<br>Request timeout: {settings.request_timeout} s; timeout attempts: {settings.timeout_retries}"
                f"<br>Endpoint: {html.escape(endpoint)}"
            )
            if route.issue:
                detail += f"<br>{html.escape(route.issue)}"
        if route.reuse_client_of:
            detail += f"<br>Reuses client from {html.escape(route.reuse_client_of)}"
        detail += (
            "<details><summary>Bridge arguments</summary><pre>"
            f"{html.escape(json.dumps(route.bridge_arguments, indent=2))}</pre></details>"
        )
        rows.append(
            f"<tr><th scope='row'>{html.escape(route.name)}</th>"
            f"<td>{html.escape(route.applicability)}</td><td>{detail}</td></tr>"
        )
    key_rows = []
    for check in report.credentials:
        guidance = (
            f"Export {check.name} in the shell that launches the run, for example "
            f"export {check.name}=... (use your own key; do not put it in this report)."
            if check.status == "missing"
            else ""
        )
        key_rows.append(
            f"<tr><th scope='row'>{html.escape(check.name)}</th>"
            f"<td>{html.escape(check.status)}</td>"
            f"<td>{html.escape(', '.join(check.routes) or 'No potentially active route')}"
            f"<p>{html.escape(guidance)}</p></td></tr>"
        )
    checked = (
        "You requested --check-environment: only named variables were checked for nonempty values."
        if report.environment_check_requested
        else "Environment values were not read. Add --check-environment to explicitly request a presence check."
    )
    return f"""<h2>Resolved static LLM routes</h2>
<p>These settings come from existing node and transport owners. Conditional means
the route is used only if execution reaches that step; task_dependent means task
composition must determine enablement; disabled and pseudo routes do not require
provider credentials. This is not a call-count or cost estimate. Proposer stage
routes are listed even when a legacy pipeline may not invoke all three.</p>
<p>Null reasoning effort means unspecified; the provider may apply its own default.
Null endpoints remain SDK/environment-controlled. Unbounded retries concern
transient errors such as 429/5xx; a finite max_retries counts total attempts,
including the first request (zero still permits the first request). Timeout attempts have a separate limit. Tuner
planner and reflector share the planner's retry policy.</p>
<table><thead><tr><th>Node / stage</th><th>Applicability</th><th>Resolved settings</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table>
<h2>Provider key names</h2><p>{html.escape(checked)}</p>
<p>No dotenv or key file is loaded. A present nonempty variable is not proof that
authentication will work. Unresolved credential names are called out in the route
table; their absence here does not mean no key is needed. Conditional routes may require a key later, even when
the current run does not ultimately reach them. Actual key values are never shown.</p>
<table><thead><tr><th>Environment name</th><th>Status</th><th>Needed by possible routes</th></tr></thead>
<tbody>{"".join(key_rows)}</tbody></table>
"""
