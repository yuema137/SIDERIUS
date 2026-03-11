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
};

// ── Plotly layout factory ────────────────────────────────────────────────────
function makePlotLayout(yLabel) {
  const t = THEMES[state.theme];
  return {
    template:   t.plotly,
    paper_bgcolor: t.paper_bg,
    plot_bgcolor:  t.plot_bg,
    font:       { color: t.text, size: 11 },
    margin:     { t: 20, r: 20, b: 50, l: 60 },
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
    legend: {
      font:        { size: 11, color: t.text },
      bgcolor:     'rgba(0,0,0,0)',
      orientation: 'h',
      y:           -0.2,
    },
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
    populateModelDropdown(cfg.models);
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

function populateModelDropdown(models) {
  const sel = document.getElementById('inp-model');
  sel.innerHTML = models.map(m => `<option value="${m}">${m}</option>`).join('');
}

// ── Series management ────────────────────────────────────────────────────────
async function addSeries() {
  const model = document.getElementById('inp-model').value.trim();
  const run   = document.getElementById('inp-run').value.trim();
  const limit = parseInt(document.getElementById('inp-limit').value) || 50;

  if (!model || !run) { alert('Please set model and run name.'); return; }

  if (state.series.find(s => s.model === model && s.run === run && s.limit === limit)) {
    alert(`Series ${model}/${run} (limit ${limit}) already added.`); return;
  }

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
      line: { color: c, width: 2 },
      marker: { color: c, size: 4 },
      connectgaps: false,
    });
    scoreTraces.push({
      x: xs, y: currentData,
      name: `${label} (current)`,
      mode: 'lines+markers',
      line: { color: c, width: 1.5, dash: 'dot' },
      marker: { color: c, size: 3 },
      connectgaps: false,
    });
    scoreTraces.push({
      x: nb.xs, y: nb.scoreYs,
      name: `${label} (new best)`,
      mode: 'markers',
      marker: { symbol: 'star', color: c, size: 14,
                line: { color: THEMES[state.theme].paper_bg, width: 1.5 } },
      visible: s.highlightBest,
      showlegend: s.highlightBest,
    });

    // Memory chart — 2 traces: memory-line, new-best stars at same x positions
    memoryTraces.push({
      x: xs, y: memData,
      name: label,
      mode: 'lines+markers',
      line: { color: c, width: 2 },
      marker: { color: c, size: 4 },
      connectgaps: false,
    });
    memoryTraces.push({
      x: nb.xs, y: nb.memYs,
      name: `${label} (new best)`,
      mode: 'markers',
      marker: { symbol: 'star', color: c, size: 14,
                line: { color: THEMES[state.theme].paper_bg, width: 1.5 } },
      visible: s.highlightBest,
      showlegend: false,
    });
  });

  const scoreLayout  = makePlotLayout('Denoising score (higher = better)');
  const memoryLayout = makePlotLayout('Model parameters');

  Plotly.react('chart-score',  scoreTraces,  scoreLayout,  PLOT_CONFIG);
  Plotly.react('chart-memory', memoryTraces, memoryLayout, PLOT_CONFIG);
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
  await Promise.all(state.series.map(loadSeriesData));
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

// ── Public API (called from HTML) ────────────────────────────────────────────
window.App = { addSeries, removeSeries, refresh, toggleTheme, setAxisType, applyRange, resetRange, toggleHighlight };

// ── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', bootstrap);
