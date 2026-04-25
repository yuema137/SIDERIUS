// SIDERIUS Dashboard — app.js
// Vanilla JS, no framework. Uses Plotly.js for interactive charts.
// Polls the FastAPI backend every N seconds.

const API = '';   // same origin — no prefix needed

// ── Colour palettes — separate per theme for optimal contrast ─────────────────
// Dark palette: vivid, high-brightness colours that pop on near-black backgrounds
// Light palette: deeper, saturated colours that stay legible on white/light-grey
const PALETTES = {
  dark: [
    '#4dabf7',  // sky blue
    '#51cf66',  // fresh green
    '#ffa94d',  // warm orange
    '#ff6b6b',  // coral red
    '#cc5de8',  // violet
    '#22d3ee',  // cyan
    '#f06595',  // rose pink
    '#a9e34b',  // lime
    '#ffd43b',  // golden yellow
    '#38d9a9',  // mint teal
  ],
  light: [
    '#1971c2',  // deep blue
    '#2f9e44',  // forest green
    '#e67700',  // burnt orange
    '#c92a2a',  // crimson
    '#862e9c',  // deep violet
    '#0891b2',  // ocean cyan
    '#d6336c',  // deep rose
    '#5c940d',  // olive green
    '#f59f00',  // amber
    '#0f766e',  // dark teal
  ],
};

function getSeriesColor(series) {
  const palette = PALETTES[state.theme];
  return palette[series.colorIndex % palette.length];
}

function getSeriesOpacity(series) {
  return series.isExploration ? state.alphaExploration : state.alphaOriginal;
}

function colorWithAlpha(hexColor, alpha) {
  // Convert #rrggbb to rgba(r,g,b,a)
  const r = parseInt(hexColor.slice(1, 3), 16);
  const g = parseInt(hexColor.slice(3, 5), 16);
  const b = parseInt(hexColor.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

function setAlpha(group, value) {
  if (group === 'original') state.alphaOriginal = value;
  else state.alphaExploration = value;
  updateCharts();
}

// ── Theme definitions ─────────────────────────────────────────────────────────
const THEMES = {
  dark: {
    plotly:   'plotly_dark',
    paper_bg: '#1a1d27',
    plot_bg:  '#1a1d27',
    grid:     '#2a2d3a',
    text:     '#e2e4ed',
    muted:    '#7a7d8e',
    css:      'dark',
    toggle:   '☀ Light',
  },
  light: {
    plotly:   'plotly_white',
    paper_bg: '#ffffff',
    plot_bg:  '#f5f6fa',
    grid:     '#dde0ea',
    text:     '#1a1d27',
    muted:    '#6b6e80',
    css:      'light',
    toggle:   '☾ Dark',
  },
};

// ── App state ────────────────────────────────────────────────────────────────
const state = {
  config:          null,
  series:          [],
  nextColorIndex:  0,
  refreshInterval: 30,
  countdownValue:  30,
  countdownTimer:  null,
  theme:           'dark',   // overridden by /api/config on load
  alphaOriginal:   1.0,
  alphaExploration: 1.0,
};

// ── Plotly layout factory ────────────────────────────────────────────────────
function makePlotLayout(yLabel) {
  const t = THEMES[state.theme];
  return {
    template:   t.plotly,
    paper_bgcolor: t.paper_bg,
    plot_bgcolor:  t.plot_bg,
    font:       { color: t.text, size: 11 },
    xaxis: {
      title:     { text: 'Research loop', font: { size: 11, color: t.muted } },
      gridcolor:  t.grid,
      tickfont:  { size: 10, color: t.muted },
      showspikes: true,
      spikemode:  'across',
    },
    yaxis: {
      title:     { text: yLabel, font: { size: 11, color: t.muted } },
      gridcolor:  t.grid,
      tickfont:  { size: 10, color: t.muted },
      showspikes: true,
    },
    showlegend: false,
    margin: { t: 20, r: 20, b: 50, l: 60 },
    hovermode: 'x unified',
  };
}

const PLOT_CONFIG = {
  responsive:   true,
  displaylogo:  false,
  modeBarButtonsToRemove: ['select2d', 'lasso2d'],
  // Built-in modebar includes: zoom, pan, box-zoom, reset axes, download PNG
};

// ── Bootstrap ────────────────────────────────────────────────────────────────
async function bootstrap() {
  // Load config (models, refresh interval, default theme)
  try {
    const cfg = await fetchJSON('/api/config');
    state.config          = cfg;
    state.refreshInterval = cfg.refresh_interval_seconds;
    state.countdownValue  = cfg.refresh_interval_seconds;
    state.theme           = cfg.theme || 'dark';
    await populateRunDropdown(cfg.models);
    await loadExplorationRuns();
    setHealth(true);
  } catch (e) {
    setHealth(false);
    console.error('Failed to load config:', e);
  }

  applyTheme(state.theme);
  initCharts();
  startCountdown();
}

function initCharts() {
  const scoreLayout  = makePlotLayout('Denoising score (higher = better)');
  const memoryLayout = makePlotLayout('Model parameters');
  Plotly.newPlot('chart-score',  [], scoreLayout,  PLOT_CONFIG);
  Plotly.newPlot('chart-memory', [], memoryLayout, PLOT_CONFIG);
}

// ── Theme ────────────────────────────────────────────────────────────────────
function applyTheme(name) {
  state.theme = name;
  const t = THEMES[name];
  document.documentElement.setAttribute('data-theme', t.css);
  document.getElementById('theme-toggle').textContent = t.toggle;
}

function toggleTheme() {
  applyTheme(state.theme === 'dark' ? 'light' : 'dark');
  updateCharts();   // re-render with new theme colours
}

async function populateRunDropdown(models) {
  // Collect all unique run names across all models
  const runSet = new Set();
  const runsPerModel = {};   // model → [run_names]

  await Promise.all(models.map(async (model) => {
    try {
      const data = await fetchJSON(`/api/models/${model}/runs`);
      const runs = data.runs || [];
      runsPerModel[model] = runs;
      runs.forEach(r => runSet.add(r));
    } catch (e) {
      runsPerModel[model] = [];
      console.warn('Failed to load runs for', model, e);
    }
  }));

  // Store for model filtering
  state.runsPerModel = runsPerModel;
  state.allModels = models;

  const runSel = document.getElementById('inp-run');
  const allRuns = Array.from(runSet).sort();
  if (allRuns.length === 0) {
    runSel.innerHTML = '<option value="">no runs found</option>';
  } else {
    runSel.innerHTML = allRuns.map(r => `<option value="${r}">${r}</option>`).join('');
  }

  // When run changes, update model dropdown to show models that have this run
  runSel.addEventListener('change', () => populateModelDropdown(runSel.value));
  if (allRuns.length > 0) populateModelDropdown(allRuns[0]);
}

function populateModelDropdown(selectedRun) {
  const modelSel = document.getElementById('inp-model');
  if (!selectedRun || !state.runsPerModel) {
    modelSel.innerHTML = '<option value="">-- select run first --</option>';
    return;
  }
  // Show only models that have this run
  const available = state.allModels.filter(m =>
    (state.runsPerModel[m] || []).includes(selectedRun)
  );
  if (available.length === 0) {
    modelSel.innerHTML = '<option value="">no models for this run</option>';
  } else {
    modelSel.innerHTML = available.map(m => `<option value="${m}">${m}</option>`).join('');
  }
}

// ── Exploration dropdowns ─────────────────────────────────────────────────────
async function loadExplorationRuns() {
  const sel = document.getElementById('inp-explore-run');
  try {
    const data = await fetchJSON('/api/exploration/runs');
    const runs = data.runs || [];
    if (runs.length === 0) {
      sel.innerHTML = '<option value="">no exploration runs</option>';
    } else {
      sel.innerHTML = runs.map(r => `<option value="${r}">${r}</option>`).join('');
      loadExplorationModels(runs[0]);
    }
    sel.addEventListener('change', () => loadExplorationModels(sel.value));
  } catch (e) {
    sel.innerHTML = '<option value="">error</option>';
  }
}

async function loadExplorationModels(runName) {
  const sel = document.getElementById('inp-explore-model');
  if (!runName) {
    sel.innerHTML = '<option value="">-- select run first --</option>';
    return;
  }
  try {
    const data = await fetchJSON(`/api/exploration/runs/${runName}/models`);
    const models = data.models || [];
    if (models.length === 0) {
      sel.innerHTML = '<option value="">no models found</option>';
    } else {
      sel.innerHTML = models.map(m => `<option value="${m}">${m}</option>`).join('');
    }
  } catch (e) {
    sel.innerHTML = '<option value="">error</option>';
  }
}

async function addExplorationSeries() {
  const run   = document.getElementById('inp-explore-run').value.trim();
  const model = document.getElementById('inp-explore-model').value.trim();
  const limit = parseInt(document.getElementById('inp-explore-limit').value) || 50;

  if (!run || !model) { alert('Please select exploration run and model.'); return; }

  // Remove duplicate if re-adding
  state.series = state.series.filter(s => !(s.model === model && s.run === run && s.limit === limit));

  const colorIndex = state.nextColorIndex++;
  const series = {
    id: `explore_${model}_${run}_${limit}_${Date.now()}`,
    model, run, limit, colorIndex,
    records: [], renderedCount: 0, runningBest: null, highlightBest: false,
    isExploration: true,
  };
  state.series.push(series);

  await loadExplorationData(series);
  renderSeriesTags();
  updateCharts();
}

async function loadExplorationData(series) {
  try {
    const url = `/api/exploration/runs/${series.run}/models/${series.model}?limit=${series.limit}&status=success`;
    const data = await fetchJSON(url);
    series.records = data.records || [];
    series.error   = null;
  } catch (e) {
    series.records = [];
    series.error   = e.message;
    console.warn(`Failed to load exploration ${series.model}/${series.run}:`, e);
  }
}

// ── Series management ────────────────────────────────────────────────────────
async function addSeries() {
  const model = document.getElementById('inp-model').value.trim();
  const run   = document.getElementById('inp-run').value.trim();
  const limit = parseInt(document.getElementById('inp-limit').value) || 50;

  if (!model || !run) { alert('Please set model and run name.'); return; }

  // Remove any existing series with the same model/run/limit before re-adding
  // (handles the case where user removes via ✕ then re-adds)
  state.series = state.series.filter(s => !(s.model === model && s.run === run && s.limit === limit));

  const colorIndex = state.nextColorIndex++;

  const series = { id: `${model}_${run}_${limit}_${Date.now()}`, model, run, limit, colorIndex, records: [], renderedCount: 0, runningBest: null, highlightBest: false };
  state.series.push(series);

  await loadSeriesData(series);
  renderSeriesTags();
  updateCharts();
}

function removeSeries(id) {
  state.series = state.series.filter(s => s.id !== id);
  renderSeriesTags();
  updateCharts();
}

async function loadSeriesData(series) {
  try {
    const url = `/api/models/${series.model}/runs/${series.run}?limit=${series.limit}&status=success`;
    const data = await fetchJSON(url);
    series.records = data.records || [];
    series.error   = null;
  } catch (e) {
    series.records = [];
    series.error   = e.message;
    console.warn(`Failed to load ${series.model}/${series.run}:`, e);
  }
}

// ── Data transformations ─────────────────────────────────────────────────────
function computeBestScoreCurve(records) {
  let best = null;
  return records.map(r => {
    const score = r.denoising_score;
    if (score !== null && score !== undefined) {
      best = best === null ? score : Math.max(best, score);
    }
    return best;
  });
}

function computeCurrentScoreCurve(records) {
  return records.map(r => {
    const score = r.denoising_score;
    return (score !== null && score !== undefined) ? score : null;
  });
}

function computeMemoryCurve(records) {
  return records.map(r => {
    const params = r.results?.model_params;
    return (params !== null && params !== undefined) ? params : null;
  });
}

// Returns {xs, scoreYs, memYs} for records that set a new best score.
// fromBest: the running best before this slice (null = no prior best).
function computeNewBestPoints(records, fromBest = null) {
  let best = fromBest;
  const xs = [], scoreYs = [], memYs = [];
  records.forEach((r, i) => {
    const score = r.denoising_score;
    if (score != null && (best === null || score > best)) {
      best = score;
      xs.push(i + 1);
      scoreYs.push(score);
      memYs.push(r.results?.model_params ?? null);
    }
  });
  return { xs, scoreYs, memYs, runningBest: best };
}

// ── Chart rendering ──────────────────────────────────────────────────────────

// Full re-render — called on addSeries, removeSeries, theme change.
// Resets renderedCount/runningBest so extendCharts knows the baseline.
function updateCharts() {
  const scoreTraces  = [];
  const memoryTraces = [];

  state.series.forEach(s => {
    const n     = s.records.length;
    const xs    = Array.from({ length: n }, (_, i) => i + 1);
    const label = `${s.model} / ${s.run}`;
    const c     = getSeriesColor(s);
    const alpha = getSeriesOpacity(s);
    const ca    = colorWithAlpha(c, alpha);

    const bestData    = computeBestScoreCurve(s.records);
    const currentData = computeCurrentScoreCurve(s.records);
    const memData     = computeMemoryCurve(s.records);
    const nb          = computeNewBestPoints(s.records);

    // Track state for incremental refresh
    s.renderedCount = n;
    s.runningBest   = bestData.length ? bestData[bestData.length - 1] : null;

    // Score chart — 3 traces: best-line, current-line, new-best stars
    scoreTraces.push({
      x: xs, y: bestData,
      name: `${label} (best)`,
      mode: 'lines+markers',
      line: { color: ca, width: 2 },
      marker: { color: ca, size: 4 },
      opacity: alpha,
      connectgaps: false,
    });
    scoreTraces.push({
      x: xs, y: currentData,
      name: `${label} (current)`,
      mode: 'lines+markers',
      line: { color: ca, width: 1.5, dash: 'dot' },
      marker: { color: ca, size: 3 },
      opacity: alpha,
      connectgaps: false,
    });
    scoreTraces.push({
      x: nb.xs, y: nb.scoreYs,
      name: `${label} (new best)`,
      mode: 'markers',
      marker: { symbol: 'star', color: ca, size: 14,
                line: { color: THEMES[state.theme].paper_bg, width: 1.5 } },
      opacity: alpha,
      visible: s.highlightBest,
      showlegend: s.highlightBest,
    });

    // Memory chart — 2 traces: memory-line, new-best stars at same x positions
    memoryTraces.push({
      x: xs, y: memData,
      name: label,
      mode: 'lines+markers',
      line: { color: ca, width: 2 },
      marker: { color: ca, size: 4 },
      opacity: alpha,
      connectgaps: false,
    });
    memoryTraces.push({
      x: nb.xs, y: nb.memYs,
      name: `${label} (new best)`,
      mode: 'markers',
      marker: { symbol: 'star', color: ca, size: 14,
                line: { color: THEMES[state.theme].paper_bg, width: 1.5 } },
      opacity: alpha,
      visible: s.highlightBest,
      showlegend: false,
    });
  });

  const scoreLayout  = makePlotLayout('Denoising score (higher = better)');
  const memoryLayout = makePlotLayout('Model parameters');

  Plotly.react('chart-score',  scoreTraces,  scoreLayout,  PLOT_CONFIG);
  Plotly.react('chart-memory', memoryTraces, memoryLayout, PLOT_CONFIG);
  renderChartLegends();
}

function renderChartLegends() {
  // Build HTML legend items — one per series, 4 per row
  const items = state.series.map(s => {
    const c = getSeriesColor(s);
    const alpha = getSeriesOpacity(s);
    const label = `${s.model} / ${s.run}`;
    const tag = s.isExploration ? '🔬' : '';
    return `<span class="chart-legend-item" style="opacity:${alpha};">
      <span class="chart-legend-dot" style="background:${c};"></span>
      <span class="chart-legend-label">${tag}${label}</span>
    </span>`;
  }).join('');

  // Render into both legend containers
  ['legend-score', 'legend-memory'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = items || '<span style="color:var(--muted);font-size:11px;">No series</span>';
  });
}

// Incremental update — called on auto-refresh.
// Only appends new data points; never resets zoom/pan/scale.
function extendCharts() {
  state.series.forEach((s, si) => {
    const newCount = s.records.length;
    if (newCount <= s.renderedCount) return;   // nothing new

    const newRecords = s.records.slice(s.renderedCount);
    const startX     = s.renderedCount + 1;
    const newXs      = newRecords.map((_, i) => startX + i);

    // Continue cumulative best from where we left off
    const prevBest = s.runningBest;   // capture before mutation
    let best = prevBest;
    const newBest = newRecords.map(r => {
      const score = r.denoising_score;
      if (score != null) best = best === null ? score : Math.max(best, score);
      return best;
    });
    s.runningBest   = best;
    s.renderedCount = newCount;

    const newCurrent = newRecords.map(r => r.denoising_score ?? null);
    const newMemory  = newRecords.map(r => r.results?.model_params ?? null);

    // New-best points in this batch (local indices 1…n → offset to global x)
    const nb = computeNewBestPoints(newRecords, prevBest);
    nb.xs = nb.xs.map(x => x + startX - 1);

    // Trace indices: score chart has 3 traces per series, memory chart has 2
    const si0 = si * 3,  si1 = si * 3 + 1,  si2 = si * 3 + 2;
    const mi0 = si * 2,  mi1 = si * 2 + 1;

    Plotly.extendTraces('chart-score',  { x: [newXs, newXs, nb.xs], y: [newBest, newCurrent, nb.scoreYs] }, [si0, si1, si2]);
    Plotly.extendTraces('chart-memory', { x: [newXs, nb.xs],        y: [newMemory, nb.memYs]             }, [mi0, mi1]);
  });
}

// ── New-best highlight toggle ─────────────────────────────────────────────────
function toggleHighlight(id) {
  const s  = state.series.find(s => s.id === id);
  if (!s) return;
  s.highlightBest = !s.highlightBest;
  const si      = state.series.indexOf(s);
  const visible = s.highlightBest;
  // score chart: trace si*3+2 | memory chart: trace si*2+1
  Plotly.restyle('chart-score',  { visible, showlegend: visible }, [si * 3 + 2]);
  Plotly.restyle('chart-memory', { visible },                      [si * 2 + 1]);
  renderSeriesTags();
}

// ── Series tags UI ───────────────────────────────────────────────────────────
function renderSeriesTags() {
  const container = document.getElementById('series-list');
  if (state.series.length === 0) {
    container.innerHTML = '<span style="color:var(--muted);font-size:12px;">No series added yet.</span>';
    return;
  }
  container.innerHTML = state.series.map(s => `
    <div class="series-tag">
      <span class="series-color-dot" style="background:${getSeriesColor(s)}"></span>
      <span>${s.model} / ${s.run} · limit ${s.limit}</span>
      ${s.error ? `<span style="color:var(--danger);font-size:11px;" title="${s.error}">⚠ error</span>` : ''}
      <button class="highlight-btn ${s.highlightBest ? 'active' : ''}"
              onclick="App.toggleHighlight('${s.id}')" title="Highlight new-best points">★</button>
      <button onclick="App.removeSeries('${s.id}')" title="Remove">✕</button>
    </div>
  `).join('');
}

// ── Refresh ──────────────────────────────────────────────────────────────────
async function refresh() {
  resetCountdown();
  await Promise.all(state.series.map(s =>
    s.isExploration ? loadExplorationData(s) : loadSeriesData(s)
  ));
  extendCharts();
  renderSeriesTags();

  try { await fetchJSON('/api/health'); setHealth(true); }
  catch { setHealth(false); }
}

function startCountdown() {
  clearInterval(state.countdownTimer);

  state.countdownValue = state.refreshInterval;
  document.getElementById('countdown').textContent = state.countdownValue;

  state.countdownTimer = setInterval(() => {
    state.countdownValue--;
    document.getElementById('countdown').textContent = Math.max(0, state.countdownValue);
    if (state.countdownValue <= 0) {
      clearInterval(state.countdownTimer);
      refresh().then(startCountdown);
    }
  }, 1000);
}

function resetCountdown() {
  clearInterval(state.countdownTimer);
  state.countdownValue = state.refreshInterval;
  document.getElementById('countdown').textContent = state.countdownValue;
}

// ── Health indicator ─────────────────────────────────────────────────────────
function setHealth(ok) {
  const dot  = document.getElementById('health-dot');
  const text = document.getElementById('health-text');
  dot.className    = 'dot' + (ok ? '' : ' warn');
  text.textContent = ok ? 'connected' : 'disconnected';
}

// ── Utilities ────────────────────────────────────────────────────────────────
async function fetchJSON(path) {
  const r = await fetch(API + path);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} — ${path}`);
  return r.json();
}

// ── Axis scale toggle ─────────────────────────────────────────────────────────
function setAxisType(divId, axis, type, btn) {
  const axisKey = axis === 'x' ? 'xaxis.type' : 'yaxis.type';
  Plotly.relayout(divId, { [axisKey]: type });
  // Update active button state within the same axis group
  const controls = btn.closest('.axis-controls');
  controls.querySelectorAll(`.axis-btn`).forEach(b => {
    if (b.getAttribute('onclick').includes(`,'${axis}',`)) {
      b.classList.remove('active');
    }
  });
  btn.classList.add('active');
}

// ── Axis range controls ───────────────────────────────────────────────────────
function applyRange(divId, prefix) {
  const xmin = document.getElementById(`${prefix}-xmin`).value;
  const xmax = document.getElementById(`${prefix}-xmax`).value;
  const ymin = document.getElementById(`${prefix}-ymin`).value;
  const ymax = document.getElementById(`${prefix}-ymax`).value;

  const update = {};
  if (xmin !== '' && xmax !== '') update['xaxis.range'] = [parseFloat(xmin), parseFloat(xmax)];
  else if (xmin !== '')           update['xaxis.range[0]'] = parseFloat(xmin);
  else if (xmax !== '')           update['xaxis.range[1]'] = parseFloat(xmax);

  if (ymin !== '' && ymax !== '') update['yaxis.range'] = [parseFloat(ymin), parseFloat(ymax)];
  else if (ymin !== '')           update['yaxis.range[0]'] = parseFloat(ymin);
  else if (ymax !== '')           update['yaxis.range[1]'] = parseFloat(ymax);

  if (Object.keys(update).length) Plotly.relayout(divId, update);
}

function resetRange(divId, prefix) {
  ['xmin','xmax','ymin','ymax'].forEach(k => {
    document.getElementById(`${prefix}-${k}`).value = '';
  });
  Plotly.relayout(divId, { 'xaxis.autorange': true, 'yaxis.autorange': true });
}

// ── Trial Details Table ─────────────────────────────────────────────────────

function populateTrialDropdowns() {
  // Reuse the same data from the main dropdowns
  const runSel = document.getElementById('trial-run');
  const mainRunSel = document.getElementById('inp-run');
  runSel.innerHTML = mainRunSel.innerHTML;

  runSel.addEventListener('change', () => {
    const modelSel = document.getElementById('trial-model');
    const selectedRun = runSel.value;
    if (!selectedRun || !state.runsPerModel) {
      modelSel.innerHTML = '<option value="">-- select run first --</option>';
      return;
    }
    const models = state.allModels.filter(m =>
      (state.runsPerModel[m] || []).includes(selectedRun)
    );
    modelSel.innerHTML = models.map(m => `<option value="${m}">${m}</option>`).join('');
  });

  if (runSel.value) runSel.dispatchEvent(new Event('change'));
}

async function loadTrialTable() {
  const run = document.getElementById('trial-run').value;
  const model = document.getElementById('trial-model').value;
  const wrap = document.getElementById('trial-table-wrap');

  if (!run || !model) {
    wrap.innerHTML = '<p style="color:var(--muted);">Select a run and model first.</p>';
    return;
  }

  wrap.innerHTML = '<p style="color:var(--muted);">Loading…</p>';

  try {
    const data = await fetchJSON(`/api/models/${model}/runs/${run}?limit=200`);
    const records = data.records || [];

    if (records.length === 0) {
      wrap.innerHTML = '<p style="color:var(--muted);">No records found.</p>';
      return;
    }

    const fmt = (v, d=2) => v != null ? Number(v).toFixed(d) : '—';
    const fmtTime = (s) => {
      if (s == null) return '—';
      if (s < 60) return `${s.toFixed(0)}s`;
      if (s < 3600) return `${(s/60).toFixed(1)}m`;
      return `${(s/3600).toFixed(1)}h`;
    };

    let html = `<table class="trial-table">
      <thead><tr>
        <th>Round</th>
        <th>Status</th>
        <th>Score</th>
        <th>Mode</th>
        <th>Trial Strategy</th>
        <th>Trial Portion</th>
        <th>Eval Strategy</th>
        <th>Eval Portion</th>
        <th>Train Portion</th>
        <th>Train Segs</th>
        <th>Eval Segs</th>
        <th>Loss Type</th>
        <th>LR</th>
        <th>Epochs</th>
        <th>Final Loss</th>
        <th>Train Time</th>
        <th>Infer Time</th>
        <th>Score Time</th>
      </tr></thead><tbody>`;

    for (const r of records) {
      const isTrial = r.is_trial;
      const mode = isTrial === true ? 'trial' : (isTrial === false ? 'formal' : '—');
      const modeClass = isTrial === true ? 'mode-trial' : (isTrial === false ? 'mode-formal' : '');
      const t = r.timing || {};
      const p = r.params || {};
      const tc = p.train_config || {};
      const lc = p.loss_config || {};
      const statusClass = r.status === 'success' ? 'status-ok' : 'status-fail';

      html += `<tr>
        <td>${r.exp_id.split('_').pop()}</td>
        <td class="${statusClass}">${r.status}</td>
        <td>${fmt(r.denoising_score, 3)}</td>
        <td class="${modeClass}">${mode}</td>
        <td>${r.trial_strategy || '—'}</td>
        <td>${fmt(r.trial_portion)}</td>
        <td>${r.eval_strategy || '—'}</td>
        <td>${fmt(r.eval_portion)}</td>
        <td>${fmt(r.train_portion)}</td>
        <td>${r.training_psd_segments != null ? r.training_psd_segments : '—'}</td>
        <td>${r.eval_psd_segments != null ? r.eval_psd_segments : '—'}</td>
        <td>${lc.loss_type || '—'}</td>
        <td>${tc.lr != null ? tc.lr : '—'}</td>
        <td>${tc.epochs != null ? tc.epochs : '—'}</td>
        <td>${fmt(r.final_loss, 4)}</td>
        <td>${fmtTime(t.train_time_s)}</td>
        <td>${fmtTime(t.inference_time_s)}</td>
        <td>${fmtTime(t.scoring_time_s)}</td>
      </tr>`;
    }

    html += '</tbody></table>';
    wrap.innerHTML = html;
  } catch (e) {
    wrap.innerHTML = `<p style="color:red;">Error: ${e.message}</p>`;
  }
}

// ── Iteration Summary Table ─────────────────────────────────────────────────

async function populateIterationDropdown() {
  const sel = document.getElementById('iter-run');
  try {
    const data = await fetchJSON('/api/exploration/runs');
    const runs = data.runs || [];
    if (runs.length === 0) {
      sel.innerHTML = '<option value="">no exploration runs</option>';
    } else {
      sel.innerHTML = runs.map(r => `<option value="${r}">${r}</option>`).join('');
    }
  } catch (e) {
    sel.innerHTML = '<option value="">error</option>';
  }
}

async function loadIterationTable() {
  const run = document.getElementById('iter-run').value;
  const wrap = document.getElementById('iter-table-wrap');

  if (!run) {
    wrap.innerHTML = '<p style="color:var(--muted);">Select an exploration run first.</p>';
    return;
  }

  wrap.innerHTML = '<p style="color:var(--muted);">Loading…</p>';

  try {
    const data = await fetchJSON(`/api/exploration/runs/${run}/iteration_table`);
    const rows = data.rows || [];
    const maxRounds = data.max_rounds || 0;

    if (rows.length === 0) {
      wrap.innerHTML = '<p style="color:var(--muted);">No iterations found for this run.</p>';
      return;
    }

    const fmt = (v, d=2) => v != null ? Number(v).toFixed(d) : '—';

    // Two-row header: top row spans the static cols + each round-block;
    // bottom row gives the per-round sub-column labels.
    let topRow = `<th rowspan="2">Iteration</th>
                  <th rowspan="2">Model</th>
                  <th rowspan="2">Status</th>`;
    let subRow = '';
    for (let i = 0; i < maxRounds; i++) {
      topRow += `<th colspan="5" class="round-group">Round ${i + 1}</th>`;
      subRow += `<th>Mode</th><th>Trial Portion</th><th>Train Portion</th><th>Final Loss</th><th>Score</th>`;
    }
    topRow += '<th rowspan="2">Termination</th>';

    let html = `<table class="trial-table iteration-table">
      <thead>
        <tr>${topRow}</tr>
        <tr>${subRow}</tr>
      </thead><tbody>`;

    for (const r of rows) {
      const statusClass = r.status === 'completed' ? 'status-ok'
                       : (r.status ? 'status-fail' : '');

      html += `<tr>
        <td>${r.iteration}</td>
        <td>${r.model_name || '—'}</td>
        <td class="${statusClass}">${r.status || '—'}</td>`;

      const rounds = r.rounds || [];
      for (let i = 0; i < maxRounds; i++) {
        const rd = rounds[i];
        if (!rd) {
          html += `<td>—</td><td>—</td><td>—</td><td>—</td><td>—</td>`;
          continue;
        }
        const mode = rd.is_trial === true ? 'trial'
                  : (rd.is_trial === false ? 'formal' : '—');
        const modeClass = rd.is_trial === true ? 'mode-trial'
                      : (rd.is_trial === false ? 'mode-formal' : '');
        html += `<td class="${modeClass}">${mode}</td>
                 <td>${fmt(rd.trial_portion)}</td>
                 <td>${fmt(rd.train_portion)}</td>
                 <td>${fmt(rd.final_loss, 4)}</td>
                 <td>${fmt(rd.denoising_score, 3)}</td>`;
      }

      html += `<td>${r.termination_reason || '—'}</td></tr>`;
    }

    html += '</tbody></table>';
    wrap.innerHTML = html;
  } catch (e) {
    wrap.innerHTML = `<p style="color:red;">Error: ${e.message}</p>`;
  }
}

// ── Public API (called from HTML) ────────────────────────────────────────────
window.App = { addSeries, addExplorationSeries, removeSeries, refresh, toggleTheme, setAxisType, applyRange, resetRange, toggleHighlight, setAlpha, loadTrialTable, loadIterationTable };

// ── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  bootstrap().then(() => {
    populateTrialDropdowns();
    populateIterationDropdown();
  });
});
