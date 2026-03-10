// SIDERIUS Dashboard — app.js
// Vanilla JS, no framework. Polls the FastAPI backend every N seconds.

const API = '';   // same origin — no prefix needed

// ── Colour palette (cycles for new series) ──────────────────────────────────
const PALETTE = [
  '#4f8ef7', '#4caf82', '#e6a43a', '#e05c5c', '#7c5cbf',
  '#38bdf8', '#f472b6', '#a3e635', '#fb923c', '#34d399',
];

// ── App state ────────────────────────────────────────────────────────────────
const state = {
  config:          null,          // FrontendConfig from /api/config
  series:          [],            // [{id, model, run, limit, color, records}]
  nextColorIndex:  0,
  refreshInterval: 30,
  countdownValue:  30,
  countdownTimer:  null,
  refreshTimer:    null,
};

// ── Chart instances ──────────────────────────────────────────────────────────
let scoreChart  = null;
let memoryChart = null;

function chartDefaults(yLabel) {
  return {
    type: 'line',
    data: { datasets: [] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 300 },
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          labels: { color: '#e2e4ed', font: { size: 11 }, boxWidth: 12, padding: 16 },
        },
        tooltip: {
          backgroundColor: '#1a1d27',
          borderColor: '#2a2d3a',
          borderWidth: 1,
          titleColor: '#e2e4ed',
          bodyColor: '#7a7d8e',
        },
      },
      scales: {
        x: {
          title: { display: true, text: 'Research loop', color: '#7a7d8e', font: { size: 11 } },
          ticks: { color: '#7a7d8e', font: { size: 10 } },
          grid:  { color: '#2a2d3a' },
        },
        y: {
          title: { display: true, text: yLabel, color: '#7a7d8e', font: { size: 11 } },
          ticks: { color: '#7a7d8e', font: { size: 10 } },
          grid:  { color: '#2a2d3a' },
        },
      },
    },
  };
}

function initCharts() {
  const ctxScore  = document.getElementById('chart-score').getContext('2d');
  const ctxMemory = document.getElementById('chart-memory').getContext('2d');
  Chart.defaults.color = '#e2e4ed';
  scoreChart  = new Chart(ctxScore,  chartDefaults('Denoising score (higher = better)'));
  memoryChart = new Chart(ctxMemory, chartDefaults('Model parameters'));
}

// ── Bootstrap ────────────────────────────────────────────────────────────────
async function bootstrap() {
  initCharts();

  // Load config (models list, refresh interval)
  try {
    const cfg = await fetchJSON('/api/config');
    state.config = cfg;
    state.refreshInterval = cfg.refresh_interval_seconds;
    state.countdownValue  = cfg.refresh_interval_seconds;
    populateModelDropdown(cfg.models);
    setHealth(true);
  } catch (e) {
    setHealth(false);
    console.error('Failed to load config:', e);
  }

  startCountdown();
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

  // Prevent duplicate
  if (state.series.find(s => s.model === model && s.run === run && s.limit === limit)) {
    alert(`Series ${model}/${run} (limit ${limit}) already added.`); return;
  }

  const color = PALETTE[state.nextColorIndex % PALETTE.length];
  state.nextColorIndex++;

  const series = { id: `${model}_${run}_${limit}_${Date.now()}`, model, run, limit, color, records: [] };
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
  // Running cumulative maximum — one value per loop, null if no score yet
  let best = null;
  return records.map(r => {
    const score = r.denoising_score;
    if (score !== null && score !== undefined) {
      best = best === null ? score : Math.max(best, score);
    }
    return best;  // null entries are skipped by Chart.js (spanGaps: false)
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

// ── Chart rendering ──────────────────────────────────────────────────────────
function updateCharts() {
  const scoreDatasets  = [];
  const memoryDatasets = [];

  // Build a shared label array (1, 2, 3, …) long enough for the longest series
  const maxLen = state.series.reduce((m, s) => Math.max(m, s.records.length), 0);
  const labels = Array.from({ length: maxLen }, (_, i) => i + 1);

  state.series.forEach(s => {
    const label = `${s.model} / ${s.run} (n=${s.limit})`;

    const scoreData   = computeBestScoreCurve(s.records);
    const currentData = computeCurrentScoreCurve(s.records);
    const memoryData  = computeMemoryCurve(s.records);

    const commonStyle = {
      borderColor:          s.color,
      backgroundColor:      s.color + '22',
      pointBackgroundColor: s.color,
      pointRadius:          3,
      pointHoverRadius:     5,
      borderWidth:          2,
      tension:              0.3,
      fill:                 false,
      spanGaps:             false,
    };

    scoreDatasets.push({ label: `${label} (best)`, data: scoreData, ...commonStyle });
    scoreDatasets.push({
      label: `${label} (current)`,
      data: currentData,
      ...commonStyle,
      borderDash: [5, 5],
      pointRadius: 2,
    });
    memoryDatasets.push({ label, data: memoryData, ...commonStyle });
  });

  scoreChart.data.labels    = labels;
  scoreChart.data.datasets  = scoreDatasets;
  memoryChart.data.labels   = labels;
  memoryChart.data.datasets = memoryDatasets;
  scoreChart.update();
  memoryChart.update();

  // Show/hide empty state
  document.getElementById('empty-score').style.display  = scoreDatasets.length  ? 'none' : '';
  document.getElementById('empty-memory').style.display = memoryDatasets.length ? 'none' : '';
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
      <span class="series-color-dot" style="background:${s.color}"></span>
      <span>${s.model} / ${s.run} · limit ${s.limit}</span>
      ${s.error ? `<span style="color:var(--danger);font-size:11px;" title="${s.error}">⚠ error</span>` : ''}
      <button onclick="App.removeSeries('${s.id}')" title="Remove">✕</button>
    </div>
  `).join('');
}

// ── Refresh ──────────────────────────────────────────────────────────────────
async function refresh() {
  resetCountdown();
  await Promise.all(state.series.map(loadSeriesData));
  updateCharts();
  renderSeriesTags();

  // Re-check health
  try { await fetchJSON('/api/health'); setHealth(true); }
  catch { setHealth(false); }
}

function startCountdown() {
  clearInterval(state.countdownTimer);
  clearTimeout(state.refreshTimer);

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
  dot.className  = 'dot' + (ok ? '' : ' warn');
  text.textContent = ok ? 'connected' : 'disconnected';
}

// ── Utilities ────────────────────────────────────────────────────────────────
async function fetchJSON(path) {
  const r = await fetch(API + path);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} — ${path}`);
  return r.json();
}

// ── Public API (called from HTML) ────────────────────────────────────────────
window.App = { addSeries, removeSeries, refresh };

// ── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', bootstrap);
