/* Configured historical evidence reader; it issues GET requests only. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let connected = false, choiceRevision = -1, readRevision = 0;
  const api = path => window.consoleSession.request(path);
  function setStatus(text) { $('recorded-example-status').textContent = text; }
  function renderFacts(rows, values) {
    rows.replaceChildren();
    for (const [label, value] of values) {
      const dt = document.createElement('dt'), dd = document.createElement('dd');
      dt.textContent = label; dd.textContent = value == null ? 'Unavailable' : String(value); rows.append(dt, dd);
    }
  }
  function render(example) {
    $('recorded-example-content').hidden = false;
    renderFacts($('recorded-example-facts'), [
      ['Candidate receipt', example.candidate_status], ['Validation passed', String(example.validation_passed)],
      ['Candidate ID', example.candidate_id], ['Native run ID', example.run_id], ['Run name', example.run_name], ['Declaration digest', example.declaration_digest],
      ['Editable source snapshot', example.source_snapshot_available ? 'Captured; not opened in this read-only view' : 'Unavailable in the captured request'],
    ]);
    const stages = example.stages.map(stage => {
      const item = document.createElement('li');
      item.textContent = `${stage.capability.toUpperCase()}: ${stage.model_type}` +
        (stage.passed === null ? '' : ` · passed: ${stage.passed}`);
      return item;
    });
    $('recorded-example-stages').replaceChildren(...stages);
    const declaration = example.declaration;
    renderFacts($('recorded-example-declaration'), [
      ['Task manifest reference', declaration.task.manifest], ['Data root reference', declaration.task.data_root],
      ['Workspace reference', declaration.task.workspace],
    ]);
    const nodes = declaration.nodes.map(node => {
      const details = document.createElement('details');
      const summary = document.createElement('summary'); summary.textContent = `${node.id} · ${node.capability.toUpperCase()}`;
      const request = document.createElement('pre'); request.textContent = JSON.stringify(node.request, null, 2);
      details.append(summary, request); return details;
    });
    $('recorded-example-nodes').replaceChildren(...nodes);
    const externals = declaration.externals.map(binding => `${binding.id} · ${binding.contract} · ${binding.location}`);
    if (externals.length) {
      const list = document.createElement('ul');
      for (const value of externals) { const item = document.createElement('li'); item.textContent = value; list.append(item); }
      $('recorded-example-nodes').prepend(list);
    }
    window.presentTokenSnapshot(example.tokens, {rows: $('recorded-token-rows'), table: $('recorded-token-table'),
      status: $('recorded-token-status'), provenance: $('recorded-token-provenance'), times: $('recorded-token-times')});
  }
  async function loadChoices() {
    if (!connected || window.consoleNavigation?.view !== 'slow-control') return;
    const revision = window.consoleSession.revision;
    try {
      const values = await api('recorded-examples');
      if (revision !== window.consoleSession.revision || !connected) return;
      const selected = $('recorded-example-choice').value;
      $('recorded-example-choice').replaceChildren();
      for (const value of values) {
        const option = document.createElement('option'); option.value = value.example_id; option.textContent = value.label;
        $('recorded-example-choice').append(option);
      }
      if (values.some(value => value.example_id === selected)) $('recorded-example-choice').value = selected;
      $('recorded-example-choice').disabled = values.length === 0;
      $('recorded-example-open').disabled = values.length === 0;
      choiceRevision = revision;
      if (!values.length) setStatus('No recorded examples are configured.');
      else if (!$('recorded-example-content').hidden) setStatus('Read-only recorded evidence shown; no operation was launched.');
      else setStatus('Choose a configured example and read its recorded evidence.');
    } catch (error) {
      if (!error.stale) setStatus('Recorded examples unavailable: ' + error.message);
    }
  }
  $('recorded-example-open').addEventListener('click', async () => {
    const id = $('recorded-example-choice').value;
    if (!connected || !id) return;
    const revision = ++readRevision;
    $('recorded-example-open').disabled = true; setStatus('Verifying captured candidate records…');
    try {
      const example = await api('recorded-examples/' + encodeURIComponent(id));
      if (revision !== readRevision || !connected) return;
      render(example); setStatus('Candidate validation evidence verified. This is not a live operation or training result.');
    } catch (error) {
      if (!error.stale && revision === readRevision) {
        $('recorded-example-content').hidden = true;
        setStatus('Recorded evidence is unavailable or failed verification: ' + error.message);
      }
    } finally {
      if (revision === readRevision) $('recorded-example-open').disabled = !connected || !$('recorded-example-choice').value;
    }
  });
  $('recorded-example-choice').addEventListener('change', () => {
    readRevision++;
    $('recorded-example-content').hidden = true;
    const id = $('recorded-example-choice').value;
    $('recorded-example-open').disabled = !connected || !id;
    setStatus(id ? 'Example changed. Read its recorded evidence to verify it.' : 'Choose a configured example.');
  });
  window.consoleSession.subscribe(state => {
    connected = state.connected; readRevision++;
    $('recorded-example-choice').disabled = !connected || choiceRevision !== state.revision;
    $('recorded-example-open').disabled = !connected || !$('recorded-example-choice').value;
    if (connected && window.consoleNavigation?.view === 'slow-control') void loadChoices();
    else if (!connected) setStatus('Disconnected. Reconnect to refresh configured examples; no operation state is inferred.');
  });
  window.addEventListener('console-view', event => {
    if (event.detail.valid && event.detail.view === 'slow-control' && connected) void loadChoices();
  });
})();
