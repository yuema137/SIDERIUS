/* Display operation and scientific evidence separately; no execution or score policy. */
(() => {
  'use strict';
  const text = value => value == null ? 'Unavailable' : typeof value === 'object' ? JSON.stringify(value) : String(value);
  function facts(rows) {
    const dl = document.createElement('dl'); dl.className = 'facts';
    for (const [label, value] of rows) {
      const dt = document.createElement('dt'), dd = document.createElement('dd');
      dt.textContent = label; dd.textContent = text(value); dl.append(dt, dd);
    }
    return dl;
  }
  function evidenceView(evidence, title, key) {
    const section = document.createElement('section'), heading = document.createElement('h3');
    heading.textContent = title; section.append(heading);
    section.append(facts([['Availability', evidence?.availability], ['Anomalies', evidence?.anomalies?.join(', ') || '(none reported)'], ['Native token sidecar ID (not aggregation)', evidence?.token_run_id]]));
    if (!evidence?.checkpoints?.length) {
      const unavailable = document.createElement('p'); unavailable.textContent = 'Checkpoint evidence unavailable.'; section.append(unavailable);
    }
    for (const checkpoint of evidence?.checkpoints || []) {
      const detail = document.createElement('details'), summary = document.createElement('summary');
      summary.textContent = `Iteration ${checkpoint.iteration}: ${text(checkpoint.native_status)} · ${checkpoint.integrity}`;
      detail.dataset.evidenceKey = key + ":" + checkpoint.iteration;
      detail.append(summary, facts([['Native status', checkpoint.native_status], ['Integrity', checkpoint.integrity],
        ['Manifest verified', checkpoint.manifest_verified], ['Artifact verified', checkpoint.artifact_verified],
        ['Formal evidence', checkpoint.formal_evidence]])); section.append(detail);
    }
    return section;
  }
  window.renderNativeChain = status => {
    const panel = document.getElementById('native-chain-observation');
    const sameOperation = panel.dataset.operationId === status?.operation_id;
    const expanded = new Set(sameOperation ? [...panel.querySelectorAll('details[open]')].map(el => el.dataset.evidenceKey) : []);
    panel.dataset.operationId = status?.operation_id || '';
    panel.replaceChildren(); panel.hidden = !['native_chain', 'native_chain_resume'].includes(status?.kind);
    if (panel.hidden) return;
    const native = status.native_chain, admission = native?.admission, supervision = native?.terminal?.supervision;
    const title = document.createElement('h2'); title.textContent = 'Native chain observations';
    const note = document.createElement('p'); note.textContent = 'Process completion and checkpoint evidence are separate facts. No scientific success verdict is inferred.';
    panel.append(title, note, facts([
      ['Operation state', status.state], ['Process', status.process?.status], ['Finishing', status.finishing], ['Reason', status.reason],
      ['Run name', admission?.run_name], ['Recipe', admission?.recipe], ['Workspace', admission?.workspace], ['Final iteration', admission?.final_iteration],
      ['Terminal execution', supervision?.execution?.status], ['Return code', supervision?.execution?.returncode],
      ['Cleanup final status', supervision?.cleanup?.final?.status], ['Direct child reaped', supervision?.direct_child_reaped],
    ]), evidenceView(native?.evidence, 'Current checkpoint evidence', 'current'));
    if (native?.terminal) {
      const terminal = document.createElement('details'), label = document.createElement('summary');
      terminal.dataset.evidenceKey = 'terminal';
      label.textContent = 'Evidence recorded at terminal time'; terminal.append(label, evidenceView(native.terminal.evidence, 'Terminal-time checkpoint evidence', 'terminal')); panel.append(terminal);
    }
    for (const detail of panel.querySelectorAll('details')) detail.open = expanded.has(detail.dataset.evidenceKey);
  };
})();
