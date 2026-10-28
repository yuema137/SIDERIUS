/* One explicit reviewed native launch intent; monitoring remains UUID-only. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id), session = window.consoleSession;
  let choices = [], review = null, generation = 0, reviewing = false, loading = false;
  let pending = null, submitting = false;
  const say = message => { $('native-chain-status').textContent = message; };
  const current = (version, revision) => version === generation && revision === session.revision && session.connected;
  function controls() {
    $('native-chain-choice').disabled = !session.connected || !choices.length;
    $('native-chain-review').disabled = !session.connected || !choices.length || !$('native-chain-choice').value || reviewing;
    $('native-chain-launch').disabled = !session.connected || !review?.credential_readiness.ready || !!pending;
    $('native-chain-retry').disabled = !session.connected || !pending || submitting || pending.accepted;
    $('native-chain-check').disabled = !session.connected || !pending;
    $('native-chain-new').disabled = !session.connected || !pending?.accepted || submitting;
    $('native-chain-intent').hidden = !pending;
  }
  function invalidate() {
    generation++; review = null; reviewing = false; $('native-chain-details').replaceChildren(); controls();
  }
  function renderReview(result) {
    const dl = document.createElement('dl'); dl.className = 'facts';
    const a = result.admission, r = result.credential_readiness;
    const rows = [['Run', a.run_name], ['Seed', result.seed], ['Recipe', a.recipe], ['Final iteration', a.final_iteration], ['Workspace', a.workspace],
      ['Capture', result.capture_path], ['Capture identity', a.capture_sha256], ['Request identity', result.request_digest],
      ['Checkout', a.checkout], ['Git directory', a.git_directory], ['Git common directory', a.git_common_directory],
      ['Original input identities', a.input_files.map(f => `${f.path}\n${f.sha256} · ${f.size_bytes} bytes`).join('\n') || '(none)'],
      ['Envelope', result.envelope], ['Read-only paths', result.read_only.join('\n') || '(none)'], ['Network', result.network],
      ['Devices', result.devices.join(', ') || '(none)'], ['Forwarded environment names', result.environment_names.join(', ') || '(none)'],
      ['Timeout seconds', result.timeout_seconds], ['Input byte limit', result.input_max_bytes],
      ['Iteration observation limit', result.max_iterations_observed], ['Result summary limit (bytes)', result.max_observation_bytes],
      ['Total result-file read limit (bytes)', result.max_evidence_read_bytes ?? `${result.max_observation_bytes} (shared with summary)`],
      ['Required credential names', r.required_names.join(', ') || '(none)'], ['Present names', r.present_names.join(', ') || '(none)'],
      ['Missing names', r.missing_names.join(', ') || '(none)'], ['Omitted names', r.omitted_names.join(', ') || '(none)'],
      ['Credential file status', r.file_status], ['Repair', r.instructions.join('\n') || '(none)']];
    for (const [label, value] of rows) {
      const dt = document.createElement('dt'), dd = document.createElement('dd'); dt.textContent = label; dd.textContent = String(value); dl.append(dt, dd);
    }
    $('native-chain-details').replaceChildren(dl);
  }
  async function loadChoices() {
    if (!session.connected || loading || window.consoleNavigation?.view !== 'home') return;
    loading = true; const version = generation, revision = session.revision, selected = $('native-chain-choice').value;
    try {
      const result = await session.request('native-chain/choices');
      if (!current(version, revision)) return;
      choices = result; $('native-chain-choice').replaceChildren(new Option('Choose a native capture', ''));
      for (const choice of choices) $('native-chain-choice').append(new Option(choice.label, choice.choice_id));
      if (choices.some(c => c.choice_id === selected)) $('native-chain-choice').value = selected;
      if (!choices.length) say('No native captures configured. Known operation UUIDs remain available in Slow control.');
    } catch (error) { if (current(version, revision)) say('Native choices unavailable: ' + error.message); }
    finally { loading = false; controls(); }
  }
  $('native-chain-choice').addEventListener('change', () => { invalidate(); say('Review this configured capture before launching. Any pending launch UUID is retained.'); });
  $('native-chain-review').addEventListener('click', async () => {
    if (!session.connected || reviewing || !$('native-chain-choice').value) return;
    invalidate(); reviewing = true; controls(); const version = generation, revision = session.revision;
    try {
      const result = await session.request('native-chain/review', {choice_id: $('native-chain-choice').value});
      if (!current(version, revision)) return;
      review = result; renderReview(result);
      say(result.credential_readiness.ready ? 'Review ready. Inspect the original capture for complete scientific settings; then explicitly launch.' : 'Launch blocked by credential readiness. Repair and review again.');
    } catch (error) { if (current(version, revision)) say('Review unavailable: ' + error.message); }
    finally { if (current(version, revision)) reviewing = false; controls(); }
  });
  async function check() {
    if (!session.connected || !pending) return;
    const intent = pending, revision = session.revision;
    try {
      const status = await session.request('operations/' + intent.payload.operation_id);
      if (pending !== intent || revision !== session.revision) return;
      if (status.kind !== 'native_chain' || status.request_digest !== intent.payload.expected_request_digest) {
        say('UUID identifies different content. Retain this UUID and inspect the operation; no new launch will be created.'); return;
      }
      intent.accepted = true; say('Admission observed. State: ' + status.state + '. Open Slow control for independent evidence.');
    } catch (error) {
      if (pending === intent && revision === session.revision && !error.stale) say('Admission remains unconfirmed: ' + error.message + '. Retry only this same retained request.');
    } finally { controls(); }
  }
  async function submit() {
    if (!session.connected || !pending || submitting || pending.accepted) return;
    const intent = pending, revision = session.revision; submitting = true; controls();
    say('Submitting native chain. This UUID is retained if the response is lost.');
    try {
      const handle = await session.request('native-chain/launch', intent.payload);
      if (revision !== session.revision || intent !== pending) return;
      intent.accepted = true; say('Native admission observed: ' + handle.observation + '. Open Slow control.');
    } catch (error) {
      if (revision === session.revision && !error.stale) { say('Submission unconfirmed or refused: ' + error.message); await check(); }
    } finally { submitting = false; controls(); }
  }
  $('native-chain-launch').addEventListener('click', () => {
    if (!session.connected || !review?.credential_readiness.ready || pending) return;
    pending = {accepted: false, payload: {choice_id: review.choice_id, operation_id: crypto.randomUUID(), expected_request_digest: review.request_digest}};
    const id = pending.payload.operation_id;
    $('native-chain-operation-id').textContent = 'Operation UUID: ' + id;
    $('native-chain-monitor').href = '#slow-control/' + id;
    try { localStorage.setItem('siderius.operation_id', id); } catch { /* URL remains available. */ }
    void submit();
  });
  $('native-chain-new').addEventListener('click', () => {
    if (!session.connected || !pending?.accepted || submitting) return;
    pending = null; invalidate();
    say('Previous admission confirmed. Its UUID remains available in Slow control. Select and review another fresh capture.');
  });
  $('native-chain-check').addEventListener('click', () => void check());
  $('native-chain-retry').addEventListener('click', () => void submit());
  session.subscribe(state => {
    invalidate(); loading = false;
    if (state.connected) { void loadChoices(); void check(); }
    else say(pending ? 'Disconnected. Pending UUID retained; reconnect to check admission.' : 'Connect to review a configured native capture.');
  });
  window.addEventListener('console-view', event => { if (event.detail.view === 'home') void loadChoices(); });
  controls();
})();
