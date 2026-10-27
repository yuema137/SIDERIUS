/* Shared read-only presentation for native and recorded candidate token snapshots. */
(() => {
  'use strict';
  function tokenCell(value, missing) {
    return (value === null ? 'Unavailable' : String(value)) + (missing ? ` · ${missing} missing` : '');
  }
  window.presentTokenSnapshot = (snapshot, target) => {
    const rows = snapshot.groups.map(group => {
      const row = document.createElement('tr');
      for (const value of [group.provider, group.requested_model, group.served_model === null ? 'Unavailable' : group.served_model,
        tokenCell(group.reported_input_tokens, group.missing_input_rows), tokenCell(group.reported_output_tokens, group.missing_output_rows),
        tokenCell(group.reported_total_tokens, group.missing_total_rows), String(group.response_rows)]) {
        const cell = document.createElement('td'); cell.textContent = value; row.append(cell);
      }
      return row;
    });
    target.rows.replaceChildren(...rows);
    target.table.hidden = rows.length === 0;
    const messages = { reported_responses: 'Reported response observations.', no_reported_responses: 'No reported responses observed.',
      native_evidence_unavailable: 'Native evidence not available yet.', usage_unavailable: 'Reported usage is unavailable.',
      preparation_not_applicable: 'Not applicable to preparation operations.' };
    target.status.textContent = (snapshot.quality.partial ? 'Partial evidence: known sums only. ' : '') +
      (snapshot.scope === 'chain_cumulative' ? 'Whole-run cumulative usage. ' : '') + messages[snapshot.reason];
    const identity = snapshot.identity_basis === 'retained_sidecar' ? 'Run identity matches retained records.' :
      snapshot.identity_basis === 'observed_sidecar' ? 'Run identity comes from its current identity file; no matching identity was retained at completion.' : '';
    target.provenance.textContent = snapshot.scope === 'chain_cumulative' ? `${snapshot.coverage_note} ${identity}` : snapshot.coverage_note;
    target.times.textContent = `Read at: ${snapshot.observed_at} · Last valid usage: ${snapshot.last_valid_usage_at || 'Unavailable'}`;
  };
})();
