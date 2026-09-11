"""The static ``index.html`` — self-contained, no dashboard required.

§V.5: *a mature example must NOT require the dashboard to be understood.*
The page references only the PNG files written beside it; there is no CDN,
no JavaScript and no server.

This module renders the projection. It decides no semantics: every direction
word, every objective label and every named absence is read from
:mod:`execute_tools.run_report`, which asked the authorities.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from execute_tools.run_report import (
    BEST_SO_FAR_POPULATION,
    AttemptView,
    RunReport,
    RunView,
)

_STYLE = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { margin: 0; padding: 2rem 1.25rem 4rem; font: 14px/1.55 -apple-system,
  BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  background: #fbfcfd; color: #1a202c; }
main { max-width: 1080px; margin: 0 auto; }
h1 { font-size: 1.5rem; margin: 0 0 .25rem; }
h2 { font-size: 1.1rem; margin: 2.25rem 0 .5rem; border-bottom: 1px solid #e2e8f0;
  padding-bottom: .3rem; }
h3 { font-size: .95rem; margin: 1.4rem 0 .4rem; }
.sub { color: #718096; font-size: .82rem; margin: 0 0 1.5rem; }
table { border-collapse: collapse; width: 100%; font-size: .82rem; margin: .5rem 0 1rem; }
th, td { text-align: left; padding: .35rem .5rem; border-bottom: 1px solid #edf2f7;
  vertical-align: top; }
th { color: #4a5568; font-weight: 600; background: #f7fafc; white-space: nowrap; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
img { max-width: 100%; height: auto; display: block; margin: .5rem 0 1rem;
  border: 1px solid #e2e8f0; border-radius: 4px; background: #fff; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .9em;
  background: #edf2f7; padding: .05rem .25rem; border-radius: 3px; }
.absent { color: #a0aec0; font-style: italic; }
.refusal { background: #fffaf0; border-left: 3px solid #dd6b20; padding: .6rem .8rem;
  margin: .6rem 0; font-size: .85rem; }
.note { color: #718096; font-size: .8rem; }
ul.gaps { font-size: .8rem; color: #718096; padding-left: 1.1rem; }
.badge { display: inline-block; padding: .05rem .4rem; border-radius: 3px;
  font-size: .75rem; background: #edf2f7; color: #4a5568; }
@media (prefers-color-scheme: dark) {
  body { background: #14181d; color: #e2e8f0; }
  h2 { border-color: #2d3748; }
  th { background: #1c222a; color: #a0aec0; }
  th, td { border-color: #242c36; }
  code, .badge { background: #242c36; color: #cbd5e0; }
  img { border-color: #2d3748; background: #fff; }
  .refusal { background: #2a2118; }
}
"""


def _esc(value: object) -> str:
    return escape("" if value is None else str(value), quote=True)


def _cell(value: object) -> str:
    """A missing value renders as a NAMED absence, never as an empty cell."""
    if value is None:
        return '<span class="absent">not recorded</span>'
    return _esc(value)


def _num(value: float | None, digits: int = 6) -> str:
    return '<span class="absent">—</span>' if value is None else f"{value:.{digits}f}"


def _figures(names: list[str], *, absent: str) -> str:
    if not names:
        return f'<p class="absent">{_esc(absent)}</p>'
    return "".join(f'<img src="{_esc(n)}" alt="{_esc(n)}">' for n in names)


def _provenance_table(report: RunReport) -> str:
    rows: list[tuple[str, str]] = []
    lock = report.lock
    if lock is not None:
        rows += [
            ("run-invariants lock", f"<code>{_esc(lock.source_path)}</code>"),
            ("resolved data scope", _cell(lock.resolved_data_scope)),
            ("health gate enabled", _cell(lock.health_gate_enabled)),
            (
                "health config sha256",
                f"<code>{_esc(lock.health_config_sha256)}</code>"
                if lock.health_config_sha256
                else _cell(None),
            ),
            (
                "task composition fingerprint",
                f"<code>{_esc(lock.task_composition_fingerprint)}</code>"
                if lock.task_composition_fingerprint
                else _cell(None),
            ),
            ("pinned at", _cell(lock.created_at)),
            ("runtime estimator", _cell(lock.runtime_estimator_identity)),
            ("runtime policy", _cell(lock.runtime_policy_identity)),
        ]
        if lock.model_plugin_identities:
            rows.append(
                (
                    "model plugin identities",
                    "<br>".join(
                        f"<code>{_esc(entry.get('model_type'))}</code> "
                        f"{_esc(entry.get('member'))} "
                        f"<code>{_esc(entry.get('content_sha256'))}</code>"
                        for entry in lock.model_plugin_identities
                    ),
                )
            )
    else:
        rows.append(
            (
                "run-invariants lock",
                '<span class="absent">no run_invariants_lock.json beside this corpus</span>',
            )
        )
    body = "".join(f"<tr><th>{_esc(k)}</th><td>{v}</td></tr>" for k, v in rows)
    return f"<table>{body}</table>"


def _attempt_row(attempt: AttemptView) -> str:
    metric_cell = (
        '<span class="absent">no identity</span>'
        if attempt.metric is None
        else f"<code>{_esc(attempt.metric.metric_id)}</code> "
        f'<span class="note">({_esc(attempt.metric.comparative)} is better)</span>'
    )
    best_cell = _num(attempt.best_so_far)
    if attempt.is_new_best:
        best_cell += ' <span class="badge">new best</span>'
    reason = attempt.failure_reason or attempt.refusal_contract_id
    return (
        "<tr>"
        f"<td><code>{_esc(attempt.exp_id)}</code></td>"
        f"<td>{_esc(attempt.status)}</td>"
        f"<td>{_esc(attempt.outcome)}</td>"
        f"<td>{'trial' if attempt.is_trial else 'formal'}</td>"
        f'<td class="num">{_num(attempt.score)}</td>'
        f'<td class="num">{best_cell}</td>'
        f"<td>{metric_cell}</td>"
        f'<td class="num">{_cell(attempt.model_params)}</td>'
        f'<td class="note">{_esc(reason) if reason else ""}</td>'
        "</tr>"
    )


def _objective_summary(attempt: AttemptView) -> str:
    objective = attempt.objective
    if objective is None:
        return '<p class="absent">no training history recorded for this attempt</p>'
    validation = (
        '<span class="absent">no validation pass recorded</span>'
        if objective.validation_objective is None
        else f"{len(objective.validation_objective)} epoch(s)"
    )
    comparability = _esc(objective.comparability)
    if objective.comparability_reason:
        comparability += f" ({_esc(objective.comparability_reason)})"
    diagnosis = (
        '<span class="absent">no diagnosis recorded</span>'
        if attempt.diagnosis is None
        else _esc(attempt.diagnosis.summary_line)
    )
    return (
        "<table>"
        f"<tr><th>objective kind</th><td><code>{_esc(objective.objective_kind)}</code> "
        f'<span class="note">(the framework\'s typed identity — not "loss")</span></td></tr>'
        f"<tr><th>reduction</th><td>{_esc(objective.objective_reduction)}</td></tr>"
        f"<tr><th>epochs</th><td>{objective.epochs_completed}/{objective.epochs_planned}"
        f"{' (truncated)' if objective.truncated else ''}</td></tr>"
        f"<tr><th>train / validation comparability</th><td>{comparability}</td></tr>"
        f"<tr><th>validation</th><td>{validation}</td></tr>"
        f"<tr><th>training dynamics</th><td>{diagnosis}</td></tr>"
        "</table>"
    )


def _health_table(attempt: AttemptView) -> str:
    if not attempt.health_gates:
        return ""
    rows = "".join(
        "<tr>"
        f"<td>{_esc(gate.display_label)}</td>"
        f"<td>{_esc(gate.execution_status)}</td>"
        f"<td>{_cell(gate.check_passed)}</td>"
        f"<td>{_esc(gate.resolved_action)}</td>"
        f"<td>{_cell(gate.check_verdicts)}</td>"
        f'<td class="note">{_esc(gate.failure_reason or "")}</td>'
        "</tr>"
        for gate in attempt.health_gates
    )
    return (
        "<h3>Health gates</h3><table><tr><th>gate</th><th>execution</th><th>passed</th>"
        "<th>resolved action</th><th>per-check verdicts</th><th>reason</th></tr>"
        f"{rows}</table>"
    )


def _secondary_table(attempt: AttemptView) -> str:
    if not attempt.secondaries:
        return ""
    rows = "".join(
        "<tr>"
        f"<td><code>{_esc(s.metric.metric_id)}</code></td>"
        f"<td>{_esc(s.metric.comparative)} is better</td>"
        f"<td>{_esc(s.status)}</td>"
        f'<td class="num">{_num(s.scalar)}</td>'
        f'<td class="note">{_esc(s.refusal_contract_id or s.error or "")}</td>'
        "</tr>"
        for s in attempt.secondaries
    )
    return (
        '<h3>Secondary metrics <span class="note">— observational; never ranked '
        "against the primary</span></h3>"
        "<table><tr><th>metric</th><th>direction</th><th>state</th><th>value</th>"
        f"<th>note</th></tr>{rows}</table>"
    )


def _observable_table(attempt: AttemptView) -> str:
    """`R-OBS-1` level 5 — the declared observables this attempt produced.

    Renders NOTHING when the run declared none, which keeps every existing
    report byte-identical. The two acquisitions are one table with an
    explicit column rather than two tables: a reader's question is "what did
    this attempt observe", and the answer is more useful undivided — while
    the column keeps WHEN each value was taken on the page, because a
    per-epoch series and a single post-training reading are not the same kind
    of evidence.
    """
    objective = attempt.objective
    dynamic = {} if objective is None else objective.observations
    if not dynamic and not attempt.static_observations:
        return ""
    rows = "".join(
        "<tr>"
        f"<td><code>{_esc(name)}</code></td>"
        "<td>dynamic</td>"
        f"<td>{len(series)} epoch(s)</td>"
        f'<td class="num">{_num(series[-1]) if series else ""}</td>'
        "</tr>"
        for name, series in sorted(dynamic.items())
    ) + "".join(
        "<tr>"
        f"<td><code>{_esc(name)}</code></td>"
        "<td>static</td>"
        "<td>after training</td>"
        f'<td class="num">{_num(value)}</td>'
        "</tr>"
        for name, value in sorted(attempt.static_observations.items())
    )
    return (
        '<h3>Observables <span class="note">— task-declared and observational; '
        "never ranked, never a budget signal</span></h3>"
        "<table><tr><th>name</th><th>acquisition</th><th>cadence</th>"
        f"<th>latest value</th></tr>{rows}</table>"
    )


def _run_section(run: RunView, figures: list[str]) -> str:
    metric_line = (
        f'<p class="note">Primary metric: <code>{_esc(run.metric.metric_id)}</code> — '
        f"{_esc(run.metric.verb)} it ({_esc(run.metric.comparative)} is better). "
        f"Identity source: <code>{_esc(run.metric_source)}</code>.</p>"
        if run.metric is not None
        else ""
    )
    refusal = (
        f'<div class="refusal">{_esc(run.ranking_refusal)}<br>'
        "<b>This run is shown without ranking, without a best-so-far and without "
        "any direction claim.</b></div>"
        if run.ranking_refusal is not None
        else ""
    )
    headline = run.headline
    head_table = (
        "<table>"
        f"<tr><th>status</th><td>{_esc(run.status)} "
        f'<span class="note">({_esc(run.termination_reason)})</span></td></tr>'
        f"<tr><th>window</th><td>{_esc(run.started_at)} &rarr; {_esc(run.finished_at)}</td></tr>"
        f"<tr><th>rounds / attempts</th><td>{run.completed_rounds} / {run.total_attempts}</td></tr>"
        f"<tr><th>best (raw)</th><td>{_num(headline.best_score)} "
        f"<code>{_esc(headline.best_exp_id)}</code></td></tr>"
        f"<tr><th>best (HealthGate-valid)</th><td>{_num(headline.best_valid_score)} "
        f"<code>{_esc(headline.best_valid_exp_id)}</code></td></tr>"
        f"<tr><th>best formal (valid)</th><td>{_num(headline.best_valid_formal_score)}</td></tr>"
        f"<tr><th>data scope</th><td>{_cell(run.provenance.resolved_data_scope)}</td></tr>"
        f"<tr><th>composed</th><td>{run.provenance.composed}"
        + (
            f" <code>{_esc(run.provenance.task_composition_fingerprint)}</code>"
            if run.provenance.task_composition_fingerprint
            else ""
        )
        + "</td></tr>"
        f"<tr><th>health config sha256</th><td>{_cell(run.provenance.health_config_sha256)}</td>"
        "</tr>"
        f"<tr><th>source</th><td><code>{_esc(run.source_path)}</code></td></tr>"
        "</table>"
    )
    attempt_rows = "".join(_attempt_row(a) for a in run.attempts)
    attempts_table = (
        "<table><tr><th>attempt</th><th>status</th><th>outcome</th><th>role</th>"
        "<th>score</th><th>best so far</th><th>metric identity</th>"
        f"<th>params</th><th>note</th></tr>{attempt_rows}</table>"
        if run.attempts
        else '<p class="absent">this run recorded no attempts</p>'
    )
    details = "".join(
        f"<h3>Attempt <code>{_esc(a.exp_id)}</code></h3>"
        f"{_objective_summary(a)}{_health_table(a)}{_secondary_table(a)}"
        f"{_observable_table(a)}"
        for a in run.attempts
    )
    return (
        f"<h2>{_esc(run.run_name)} &middot; {_esc(run.model_type)}</h2>"
        f"{metric_line}{refusal}{head_table}"
        f"{_figures(figures, absent='no per-epoch training history recorded for this run')}"
        f"{attempts_table}{details}"
    )


def render_html(report: RunReport, figures: dict[str, list[str]]) -> str:
    """The whole report as one self-contained HTML document."""
    objective_figures = figures.get("objective_history", [])
    runs_html = "".join(
        _run_section(run, [objective_figures[i]] if i < len(objective_figures) else [])
        for i, run in enumerate(report.runs)
    )
    trajectory = report.trajectory
    trajectory_note = (
        f'<div class="refusal">{_esc(trajectory.refusal)}<br>'
        "<b>No trajectory chart is drawn.</b> A best-so-far curve without a "
        "declared direction would be confidently wrong.</div>"
        if trajectory.refusal is not None
        else (
            f'<p class="note">Ordered by <code>{_esc(trajectory.metric.metric_id)}</code>; '
            f"{_esc(trajectory.metric.comparative)} is better. Population: "
            f"{_esc(BEST_SO_FAR_POPULATION)}.</p>"
            if trajectory.metric is not None
            else ""
        )
    )
    unreadable = (
        '<h2>Artifacts that were found but are not consumable</h2><ul class="gaps">'
        + "".join(f"<li>{_esc(item)}</li>" for item in report.unreadable)
        + "</ul>"
        if report.unreadable
        else ""
    )
    gaps = "".join(f"<li>{_esc(item)}</li>" for item in report.gaps)
    workspace = (
        f"<code>{_esc(report.workspace)}</code>" if report.workspace else "explicit artifact paths"
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SIDERIUS run report</title><style>{_STYLE}</style></head>
<body><main>
<h1>SIDERIUS run report</h1>
<p class="sub">Generated {_esc(report.generated_at)} from {workspace} &middot;
projection schema <code>{_esc(report.schema_version)}</code> &middot;
{len(report.runs)} run(s).<br>
Every value below is read from persisted <code>run_output_*.json</code>
artifacts. Nothing is simulated, and no new field was persisted to draw it.</p>

<h2>Primary metric trajectory</h2>
{trajectory_note}
{
        _figures(
            figures.get("primary_metric_trajectory", []),
            absent="no scored, rankable attempt in this corpus",
        )
    }

<h2>Attempt outcomes</h2>
{_figures(figures.get("status_breakdown", []), absent="no attempts recorded")}

<h2>Secondary metrics</h2>
{_figures(figures.get("secondary_metrics", []), absent="this corpus declares no secondary metric")}

<h2>Reproducibility identity</h2>
{_provenance_table(report)}

{runs_html}
{unreadable}

<h2>What this report deliberately does not show</h2>
<p class="note">These are class-B gaps: information the framework does not
persist. None of them may become a new persisted semantic in order to improve
a plot &mdash; the view does without it, and the gap is recorded here.</p>
<ul class="gaps">{gaps}</ul>
</main></body></html>
"""


def write_html(report: RunReport, figures: dict[str, list[str]], out_dir: Path) -> Path:
    """Write ``index.html`` into ``out_dir`` and return its path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "index.html"
    path.write_text(render_html(report, figures), encoding="utf-8")
    return path
