/* Render only the native per-body report projection; no score is recomputed here. */
(() => {
  'use strict';
  const value = item => item == null ? 'Unavailable' : String(item);
  function facts(rows) {
    const list = document.createElement('dl'); list.className = 'facts';
    for (const [label, content] of rows) {
      const term = document.createElement('dt'), detail = document.createElement('dd');
      term.textContent = label; detail.textContent = value(content);
      // Display rounding only; the exact reported number stays available as a tooltip.
      if (typeof content === 'number' && window.consoleNumbers?.differs(content)) {
        detail.textContent = window.consoleNumbers.format(content);
        detail.title = 'Exact reported value: ' + window.consoleNumbers.exact(content);
        detail.dataset.exact = window.consoleNumbers.exact(content);
      }
      list.append(term, detail);
    }
    return list;
  }
  function metricLabel(metric) {
    return metric ? `${metric.metric_id} (${metric.comparative} is better)` : 'Unavailable';
  }
  function renderRun(run) {
    const section = document.createElement('details'), summary = document.createElement('summary');
    summary.textContent = `${run.model_type} · ${run.status} · ${run.total_attempts} attempts`;
    section.append(summary, facts([
      ['Run', run.run_name], ['Status', run.status], ['Termination', run.termination_reason],
      ['Started', run.started_at], ['Finished', run.finished_at],
      ['Completed rounds', run.completed_rounds], ['Reported attempts', run.total_attempts],
      ['Metric', metricLabel(run.metric)], ['Metric source', run.metric_source],
      ['Best experiment', run.headline.best_exp_id], ['Best score', run.headline.best_score],
      ['Best formal score', run.headline.best_formal_score],
      ['Best valid experiment', run.headline.best_valid_exp_id],
      ['Best valid score', run.headline.best_valid_score],
      ['Best valid formal score', run.headline.best_valid_formal_score],
      ['Reported status counts', Object.entries(run.status_counts || {}).map(([key, count]) => `${key}: ${count}`).join(', ') || 'Unavailable'],
    ]));
    if (run.ranking_refusal) {
      const note = document.createElement('p'); note.className = 'muted';
      note.textContent = run.ranking_refusal; section.append(note);
    }
    if (run.secondary_metrics?.length) {
      const secondary = document.createElement('p'); secondary.className = 'muted';
      secondary.textContent = 'Secondary metrics: ' + run.secondary_metrics.map(metricLabel).join('; ');
      section.append(secondary);
    }
    return section;
  }
  window.renderGraphResults = (projection, errorMessage = '') => {
    const panel = document.getElementById('graph-results-observation');
    panel.replaceChildren(); panel.hidden = true;
    if (errorMessage) {
      panel.hidden = false;
      const heading = document.createElement('h2'); heading.textContent = 'Workflow training results';
      const message = document.createElement('p'); message.setAttribute('role', 'status'); message.textContent = errorMessage;
      panel.append(heading, message); return;
    }
    if (!projection?.available) return;
    panel.hidden = false;
    const heading = document.createElement('h2'); heading.textContent = 'Workflow training results';
    const note = document.createElement('p'); note.className = 'muted';
    note.textContent = 'Native tuner reports are shown separately for each verified workflow body. No cross-iteration score is calculated.';
    panel.append(heading, note);
    if (!projection.bodies.length) {
      const empty = document.createElement('p'); empty.textContent = 'No verified workflow body was recorded, so no score is available.'; panel.append(empty); return;
    }
    for (const body of projection.bodies) {
      const group = document.createElement('section'); group.className = 'graph-result-body';
      const title = document.createElement('h3');
      title.textContent = projection.bodies.length > 1 ? `Iteration ${body.iteration}` : 'Workflow body';
      const stage = window.editorCapabilityPresentation?.label('tuning') || 'tuning';
      group.append(title, facts([[`${stage} state`, body.tuning_state]]));
      if (body.result) group.append(renderRun(body.result));
      else {
        const unavailable = document.createElement('p'); unavailable.className = 'muted';
        unavailable.textContent = 'No score is available: this body has no succeeded native tuning record.'; group.append(unavailable);
      }
      panel.append(group);
    }
  };
})();
