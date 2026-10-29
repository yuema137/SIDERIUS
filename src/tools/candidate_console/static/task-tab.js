/* Task tab: the configured task list and a read-only panel of one task's summary.
 * Presentation only. Facts come from GET /api/tasks/{id}/summary (task_summary.py owns
 * them); every server string is written with textContent. Selection is task-selection.js. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const session = window.consoleSession, selection = window.consoleTask;
  const POLL_MS = 1000;
  const EMPTY = 'No task is configured. Add your task to siderius_workspace/settings/console.json, then restart the console. ';
  const SETUP_GUIDE = 'https://github.com/yuema137/SIDERIUS/blob/master/src/tools/candidate_console/README.md#set-up-and-open-the-console';
  const UNAVAILABLE = {
    sandbox_missing: 'The task sandbox is not available on this machine, so the task package cannot be read.',
    data_root_missing: "The task's data folder does not exist.",
    manifest_missing: "The task's manifest cannot be read.",
    llm_config_unreadable: "The task's model profile cannot be read."
  };
  let summary = null, counted = null, failure = '', counting = false, timer = null, countTimer = null, shownFor = null;

  function el(tag, text, parent, className) {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null && text !== '') node.textContent = text;
    if (className) node.className = className;
    if (parent) parent.append(node);
    return node;
  }
  const count = value => Number(value).toLocaleString('en-US');
  function size(bytes) {
    const units = ['bytes', 'KB', 'MB', 'GB', 'TB'];
    let value = Number(bytes), unit = 0;
    while (value >= 1000 && unit < units.length - 1) { value /= 1000; unit++; }
    return unit ? `${value.toFixed(value < 10 ? 1 : 0)} ${units[unit]}` : `${count(bytes)} bytes`;
  }
  function duration(seconds) {
    const value = Number(seconds);
    if (value >= 3600 && value % 60 === 0) return `${Number((value / 3600).toFixed(2))} h (${count(value)} s)`;
    if (value >= 60 && value % 60 === 0) return `${value / 60} min (${count(value)} s)`;
    return `${count(value)} s`;
  }
  const json = value => typeof value === 'string' ? value : JSON.stringify(value);
  const human = name => name.replace(/_/g, ' ').replace(/^./, first => first.toUpperCase());

  // --- Building blocks ---------------------------------------------------------------
  function section(parent, title, id) {
    const box = el('section', '', parent, 'task-section'); box.id = id;
    el('h3', title, box); return box;
  }
  function facts(parent, rows) {
    const list = el('dl', '', parent, 'facts task-facts');
    for (const [term, value, className] of rows) {
      el('dt', term, list);
      const dd = el('dd', '', list, className);
      if (value instanceof Node) dd.append(value); else dd.textContent = value;
    }
    return list;
  }
  function table(parent, headings, rows, id) {
    const wrap = el('div', '', parent, 'task-table'), grid = el('table', '', wrap);
    if (id) grid.id = id;
    const head = el('tr', '', el('thead', '', grid));
    for (const heading of headings) el('th', heading, head).scope = 'col';
    const body = el('tbody', '', grid);
    for (const row of rows) {
      const line = el('tr', '', body);
      for (const cell of row) {
        const td = el('td', '', line);
        if (cell instanceof Node) td.append(cell); else td.textContent = cell;
      }
    }
    return grid;
  }
  const mono = text => el('span', text, null, 'mono');
  const badge = (text, kind) => el('span', text, null, `task-badge ${kind}`);
  const note = (parent, text, className = 'muted') => el('p', text, parent, className);

  // --- Task list -----------------------------------------------------------------------
  function renderList() {
    const box = $('task-list'); box.replaceChildren();
    if (!session.connected) { note(box, 'Connect to see the configured tasks.'); return; }
    if (selection.state === 'loading' || selection.state === 'idle') { note(box, 'Loading tasks…').setAttribute('role', 'status'); return; }
    if (selection.state === 'error') {
      el('p', `Tasks could not be loaded: ${selection.error}`, box, 'warning').id = 'task-list-error';
      const retry = el('button', 'Retry', box, 'secondary'); retry.type = 'button'; retry.id = 'task-list-retry';
      retry.addEventListener('click', () => selection.reload());
      return;
    }
    if (!selection.tasks.length) {
      const empty = el('p', EMPTY, box, 'empty-state task-list-empty'); empty.id = 'task-list-empty';
      const link = el('a', 'How to add a task (step 2)', empty); link.href = SETUP_GUIDE; link.target = '_blank'; link.rel = 'noopener noreferrer';
      return;
    }
    const list = el('ul', '', box, 'task-items');
    for (const task of selection.tasks) {
      const button = el('button', '', el('li', '', list), 'task-item'); button.type = 'button';
      button.dataset.taskId = task.task_id;
      button.setAttribute('aria-pressed', String(task.task_id === selection.selectedId));
      el('span', task.label, button, 'task-item-label');
      el('span', task.revision ? `Version ${task.revision}` : 'unversioned', button, 'task-item-revision');
      button.addEventListener('click', () => selection.select(task.task_id));
    }
  }

  // --- Summary requests ----------------------------------------------------------------
  const path = (id, query = '') => `tasks/${encodeURIComponent(id)}/summary${query}`;
  // Read on the Task tab, and on Workflow for the metric suggestions of stop conditions.
  const active = () => session.connected && ['task', 'workflow'].includes(window.consoleNavigation?.view);
  // Metric ids the task declares (main score first) for the loop's metric-threshold field.
  function metricIds() {
    const pkg = summary?.state === 'ready' && summary.task_id === selection.selectedId ? summary.package : null;
    return pkg ? [pkg.main_score.metric_id, ...pkg.observational_metrics.map(metric => metric.metric_id)] : [];
  }
  function publishMetrics() {
    const list = $('task-metric-ids'), ids = metricIds();
    if ([...list.options].map(option => option.value).join('\n') === ids.join('\n')) return;
    list.replaceChildren(...ids.map(id => { const option = document.createElement('option'); option.value = id; return option; }));
  }
  async function read(query = '') {
    const id = selection.selectedId, revision = session.revision;
    if (!id || !session.connected) return;
    clearTimeout(timer); timer = null;
    try {
      const view = await session.request(path(id, query));
      if (id !== selection.selectedId || revision !== session.revision) return;
      summary = view; failure = '';
      // Poll the plain URL while the sandboxed observation runs (never re-send refresh=1).
      if (view.state === 'observing' && active()) timer = setTimeout(() => void read(), POLL_MS);
    } catch (error) {
      if (error.stale || id !== selection.selectedId || revision !== session.revision) return;
      failure = `The task summary could not be loaded: ${error.message}`;
    }
    renderPanel();
  }
  async function countSamples() {
    const id = selection.selectedId, revision = session.revision;
    if (!id || !session.connected) return;
    clearTimeout(countTimer); countTimer = null; counting = true; renderPanel();
    try {
      const view = await session.request(path(id, '?count_samples=1'));
      if (id !== selection.selectedId || revision !== session.revision) return;
      counted = view;
      if (view.state === 'observing' && session.connected) { countTimer = setTimeout(() => void countSamples(), POLL_MS); return; }
      counting = false;
    } catch (error) {
      if (error.stale || id !== selection.selectedId || revision !== session.revision) return;
      counting = false; counted = {state: 'failed', failure: {stage: 'console', message: error.message}};
    }
    renderPanel();
  }

  // --- Panel sections (order is the contract's) ------------------------------------------
  function identity(parent, view, item) {
    const box = section(parent, 'Identity', 'task-identity'), pkg = view.package;
    const pin = pkg?.identity.task_revision;
    const version = pin ? `${pin.package_id} · ${pin.revision}` : item?.revision ? `Version ${item.revision}` : 'Unversioned (no task_revision in the console configuration)';
    facts(box, [['Label', view.label], ['Task id', mono(view.task_id)], ['Version', version]]);
    if (pkg?.identity.revision_matches === false) note(box, 'The configured version does not match the task package on disk. Ask your coding agent to update task_revision or restore the package.', 'warning');
    if (pkg?.description) note(box, pkg.description, 'task-description');
    if (pkg) {
      const details = el('details', '', box, 'task-fingerprint'); el('summary', 'Fingerprint', details);
      facts(details, [['Semantic fingerprint', mono(pkg.identity.semantic_fingerprint)], ['Data path', mono(pkg.identity.task_data_path_id)]]);
    }
  }
  function scopeLine(volume) {
    return volume ? `${count(volume.file_count)} file${volume.file_count === 1 ? '' : 's'} · ${size(volume.expected_on_disk_bytes)}` : 'not declared by this task';
  }
  function data(parent, view) {
    const box = section(parent, 'Data', 'task-data'), volume = view.data_volume, pkg = view.package;
    const rows = [['Data folder', mono(view.data_root)]];
    if (volume) {
      rows.push(['Files', count(volume.files) + (volume.complete ? '' : ' (at least)')]);
      const total = el('span', size(volume.bytes) + (volume.complete ? '' : ' (at least)')); total.title = `${count(volume.bytes)} bytes`;
      rows.push(['Total size', total]);
    } else rows.push(['Files', 'Not counted yet']);
    if (pkg?.partition_count !== null && pkg?.partition_count !== undefined) rows.push(['Partitions', count(pkg.partition_count)]);
    if (pkg) {
      const scopes = pkg.scopes;
      if (scopes.state === 'declared') rows.push(['Training split', scopeLine(scopes.training)], ['Evaluation split', scopeLine(scopes.evaluation)]);
      else if (scopes.state === 'not_declared') rows.push(['Training and evaluation split', 'not declared by this task']);
      else rows.push(['Training and evaluation split', `could not be read: ${scopes.message || 'no message'}`]);
    }
    facts(box, rows);
    if (volume && !volume.complete) note(box, `The count is incomplete: it stops after ${count(volume.entry_cap)} entries, and unreadable folders are skipped.`);
    if (pkg?.scopes.basis) note(box, pkg.scopes.basis, 'muted task-basis');
    if (!pkg) return;
    const actions = el('div', '', box, 'actions task-count');
    const button = el('button', counting ? 'Counting samples…' : 'Count samples', actions, 'secondary'); button.type = 'button';
    button.id = 'task-count-samples'; button.disabled = counting || !session.connected;
    button.addEventListener('click', () => void countSamples());
    el('span', 'Reads the data in the task sandbox; it may take a while.', actions, 'muted');
    const result = el('div', '', box); result.id = 'task-sample-counts';
    if (!counted || counting) return;
    const samples = counted.package?.sample_counts;
    if (counted.state === 'ready' && samples?.state === 'counted') {
      facts(result, [['Training samples', samples.training === null ? 'not counted' : count(samples.training)],
        ['Evaluation samples', samples.evaluation === null ? 'not counted' : count(samples.evaluation)]]);
    } else if (counted.state === 'ready' && samples?.state === 'not_countable') {
      note(result, "This task's datasets do not report how many samples they hold." + (samples.message ? ` ${samples.message}` : ''));
    } else {
      const message = samples?.message || counted.failure?.message || counted.unavailable?.hint || 'no message';
      note(result, `Samples could not be counted: ${message}`, 'warning');
    }
  }
  const IO_LABELS = {input_shape: 'Input shape', input_description: 'Input', output_shape: 'Output shape', output_description: 'Output'};
  function modelIo(parent, pkg) {
    const box = section(parent, 'Model input and output', 'task-model-io');
    const rows = Object.entries(pkg.model_io || {}).filter(([, value]) => value !== '' && value !== null && value !== 0)
      .map(([name, value]) => [IO_LABELS[name] || human(name), typeof value === 'string' && name.endsWith('_shape') ? mono(value) : json(value)]);
    if (rows.length) facts(box, rows); else note(box, 'Not declared by this task.');
  }
  function objective(parent, pkg) {
    const box = section(parent, 'Objective', 'task-objective');
    if (pkg.objective_source === 'planner_chooses' || !pkg.objective) { note(box, 'Not fixed by the task: the planner chooses the training objective.'); return; }
    facts(box, Object.entries(pkg.objective).filter(([, value]) => value !== null).map(([name, value]) => [human(name), json(value)]));
  }
  const direction = value => ({higher: 'Higher is better', lower: 'Lower is better'})[value] || value;
  function mainScore(parent, pkg) {
    const box = section(parent, 'Main score', 'task-main-score'), score = pkg.main_score;
    facts(box, [['Metric', mono(score.metric_id)], ['Direction', direction(score.direction)], ['Aggregation', mono(score.aggregation)]]);
    if (!pkg.observational_metrics.length) return;
    note(box, 'Recording metrics are measured and stored but never decide which candidate is best.');
    table(box, ['Metric', 'Direction', 'Aggregation', 'Use'], pkg.observational_metrics.map(metric =>
      [mono(metric.metric_id), direction(metric.direction), mono(metric.aggregation), badge('Recording', 'recording')]), 'task-observational-metrics');
  }
  function health(parent, pkg) {
    const box = section(parent, 'Health checks', 'task-health'), gates = pkg.health.gates;
    if (!gates.length) { note(box, 'This task declares no Health checks.'); return; }
    note(box, 'A Blocking check that fails makes the candidate invalid. A Recording check is only recorded.');
    table(box, ['Gate', 'Checks', 'Effect'], gates.map(gate => [mono(gate.gate_id), gate.checks.join(', ') || '—',
      gate.role === 'blocking' ? badge('Blocking', 'blocking') : gate.role === 'observational' ? badge('Recording', 'recording') : badge('Undeclared', 'undeclared')]), 'task-health-gates');
  }
  const ROLES = {task_data_path: 'Task data', primary_metric: 'Main score', model_plugin: 'Model', unrecorded: 'Unrecorded'};
  function plugins(parent, pkg) {
    const box = section(parent, 'Evaluation and model plugins', 'task-plugins');
    if (!pkg.plugins.length) note(box, 'This task declares no plugins.');
    else table(box, ['Reference', 'Symbol', 'Role'], pkg.plugins.map(plugin =>
      [mono(plugin.configured_ref), mono(plugin.symbol), plugin.roles.map(role => ROLES[role] || human(role)).join(', ')]), 'task-plugin-table');
    if (pkg.model_types.length) facts(box, [['Model types', pkg.model_types.join(', ')]]);
  }
  const RULES = {exact: 'Fixed to', range: 'Range', allowed: 'One of', predicate: 'Condition'};
  function locked(parent, pkg) {
    const box = section(parent, 'Locked parameters', 'task-locked');
    if (!pkg.locked_parameters.length) { note(box, 'This task locks no parameters; the planner may change them.'); return; }
    note(box, 'The task fixes these settings; a workflow cannot change them.');
    table(box, ['Parameter', 'Rule', 'Value'], pkg.locked_parameters.map(item => [mono(item.path), RULES[item.rule] || item.rule, mono(json(item.value))]), 'task-locked-table');
  }
  function deliverable(parent, pkg) {
    const box = section(parent, 'Deliverable', 'task-deliverable');
    if (!pkg.deliverable) { note(box, 'Not declared by this task: the task names its own outputs.'); return; }
    facts(box, Object.entries(pkg.deliverable).map(([name, value]) => [human(name), mono(json(value))]));
  }
  function runPolicy(parent, view) {
    const box = section(parent, 'Run policy', 'task-run-policy'), policy = view.run_policy;
    const gpus = window.consoleCompute.gpuDevices(policy.candidate_devices);
    facts(box, [
      ['Preparation time limit', duration(policy.preparation_timeout_seconds)],
      ['Candidate time limit', duration(policy.candidate_timeout_seconds)],
      ['Network', policy.candidate_network ? 'Allowed' : 'Blocked'],
      ['Devices', policy.candidate_devices.length ? mono(policy.candidate_devices.join(', ')) : 'None'],
      ['GPU', gpus.length ? `Passed into the run sandbox (${gpus.join(', ')})` : el('span', window.consoleCompute.gpuWarning, null, 'task-gpu-warning')],
      ['Credential names', policy.candidate_environment_names.length ? mono(policy.candidate_environment_names.join(', ')) : 'None'],
      ['Allowed output types', policy.allowed_output_types ? policy.allowed_output_types.join(', ') : 'Any']
    ]);
    note(box, 'Only the names of credentials are shown; their values never reach this page.');
  }
  function stateLine(parent, view) {
    const line = el('div', '', parent, 'task-state'); line.id = 'task-summary-state'; line.dataset.state = view.state;
    line.setAttribute('role', 'status');
    if (view.state === 'observing') el('p', 'Reading the task package in the sandbox…', line, 'muted');
    else if (view.state === 'failed') {
      el('p', `The task package could not be read (stage: ${view.failure?.stage || 'unknown'}).`, line, 'warning');
      if (view.failure?.message) el('pre', view.failure.message, line, 'task-failure-message');
      el('p', 'Fix the task package with your coding agent, then press Refresh.', line, 'muted');
    } else if (view.state === 'unavailable') {
      el('p', UNAVAILABLE[view.unavailable?.reason] || 'The task summary is not available.', line, 'warning');
      if (view.unavailable?.hint) el('p', view.unavailable.hint, line, 'task-hint');
    }
  }

  function renderPanel() {
    publishMetrics();
    const body = $('task-panel-body'), item = selection.selected;
    body.replaceChildren();
    $('task-refresh').disabled = !session.connected || !item || summary?.state === 'observing';
    $('task-panel-heading').textContent = item ? item.label : 'Task details';
    if (!session.connected) { note(body, 'Connect, then choose a task to see its details.'); return; }
    if (!item) { note(body, selection.tasks.length ? 'Choose a task on the left to see its details.' : 'No task to show.'); return; }
    if (failure) { el('p', failure, body, 'warning').id = 'task-summary-error'; return; }
    if (!summary || summary.task_id !== item.task_id) { note(body, 'Loading the task summary…').setAttribute('role', 'status'); return; }
    stateLine(body, summary);
    identity(body, summary, item);
    data(body, summary);
    const pkg = summary.package;
    if (pkg) { modelIo(body, pkg); objective(body, pkg); mainScore(body, pkg); health(body, pkg); plugins(body, pkg); locked(body, pkg); deliverable(body, pkg); }
    runPolicy(body, summary);
  }

  function sync() {
    renderList();
    const id = selection.selectedId;
    if (id !== shownFor) {
      shownFor = id; summary = null; counted = null; counting = false; failure = '';
      clearTimeout(timer); clearTimeout(countTimer);
    }
    if (id && active() && (!summary || (summary.state === 'observing' && !timer))) void read();
    renderPanel();
  }
  $('task-refresh').addEventListener('click', () => { counted = null; void read('?refresh=1'); });
  window.consoleTaskSummary = Object.freeze({get mainMetricId() { return metricIds()[0] || null; }});
  window.addEventListener('console-task', sync);
  window.addEventListener('console-view', sync);
  session.subscribe(sync);
  sync();
})();
