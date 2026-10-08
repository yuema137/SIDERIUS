"""Escaped local HTML for an advisory review or an explicit skip."""

import html

from tools.setup_review.semantic_models import SemanticReviewReceipt


def render_semantic_review(receipt: SemanticReviewReceipt) -> str:
    esc = html.escape
    body = f"<h2>Outcome: {esc(receipt.outcome)}</h2>"
    if receipt.skip_reason is not None:
        body += f"<p>Explicit skip reason: {esc(receipt.skip_reason)}</p>"
    if receipt.failure_category is not None:
        body += f"<p>{esc(receipt.failure_category)}: {esc(receipt.failure_action or '')}</p>"
    if receipt.judgement is not None:
        body += f"<p>{esc(receipt.judgement.summary)}</p><h2>Findings</h2>"
        if not receipt.judgement.findings:
            body += "<p>The model reported no findings. This does not establish readiness.</p>"
        for finding in receipt.judgement.findings:
            body += (
                f"<article><h3>{esc(finding.severity)}: {esc(finding.field)}</h3>"
                f"<p>{esc(finding.explanation)}</p>"
                f"<p>Suggested correction: {esc(finding.suggested_correction)}</p>"
                f"<p>Uncertainty: {esc(finding.uncertainty)}</p></article>"
            )
        body += "<h2>Additional checks named by the model</h2><ul>"
        body += "".join(f"<li>{esc(item)}</li>" for item in receipt.judgement.uncovered_checks)
        body += "</ul>"
    limits = "".join(f"<li>{esc(item)}</li>" for item in receipt.limitations)
    transmitted = (
        '<a href="system.txt">System prompt</a> · <a href="user.txt">User prompt</a>'
        if receipt.system_sha256
        else "No prompt was sent by this operation."
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SIDERIUS optional setup review</title><style>
body {{font:16px/1.5 system-ui;max-width:960px;margin:2rem auto;padding:0 1rem;overflow-wrap:anywhere}}
article {{border:1px solid #bbc;padding:1rem;margin:1rem 0}} .notice {{background:#fff2cc;padding:1rem}}
</style></head><body><h1>Optional setup snapshot review</h1>
<p class="notice">Advisory review only. This page does not approve or launch an experiment.</p>
<h2>Snapshot reviewed or skipped</h2><p>{esc(receipt.source_report)}</p>
<p>SHA-256: <code>{esc(receipt.source_sha256)}</code></p>
<p>Original deterministic outcome: <strong>{esc(receipt.deterministic_outcome)}</strong>.</p>
{body}<h2>Checks still outside this review</h2><ul>{limits}</ul>
<h2>Saved evidence</h2><p><a href="receipt.json">Typed receipt</a> ·
<a href="packet.json">Selected review data</a></p><p>{transmitted}</p>
<p>Inspect the exact text before sharing it. Follow your original launcher after completing
the remaining checks; this receipt does not detect later edits or bypass runtime validation.</p>
</body></html>"""
