# Dashboard first-run UX audit

**Audited at**: `c991d6f6` (`origin/master`, 2026-08-24), read-only.
**Ownership**: dashboard *production* files (`dashboard/**`) are owned by the
in-flight PR-12e stream. Nothing here edits them; every finding is a
**post-12e implementation candidate**. The user-facing operational caveats are
already documented in [the dashboard guide](../guides/dashboard.md).
**Method**: every claim was verified against source at this commit; the three
inherited finding IDs (F-12e-UX-3/-4/-6) were re-verified rather than assumed.

File inventory: `main.py` (188), `settings.py` (110), `api/router.py` (611),
`api/models.py` (245), `data_sources/local_json.py` (313), `static/app.js`
(865), `static/index.html` (195), `static/style.css` (256).

---

## 1. Inherited findings — all three CONFIRMED

### F-12e-UX-3 — frontend hardcodes higher-is-better (5 JS sites + 1 label)

| site | expression |
|---|---|
| `static/app.js:345` | `best = best === null ? score : Math.max(best, score);` |
| `static/app.js:372` | `if (score != null && (best === null || score > best))` |
| `static/app.js:503` | `best = best === null ? score : Math.max(best, score);` |
| `static/app.js:154` | `makePlotLayout('Denoising score (higher = better)')` |
| `static/app.js:459` | same label, exploration chart |
| `static/index.html:95` | caption "… Higher is better" |

None consults `metric_result.direction`. The asymmetry is the finding: the
Python half was made direction-aware in Step 10 P2a (`local_json.py:18-22,
207, 214, 276, 283` route through `metric_identity_from_record` /
`corpus_order`), the JS half was not. On a lower-is-better task the API ranks
correctly while the chart's "cumulative best" climbs the wrong way under a
caption asserting the opposite.

### F-12e-UX-4 — the parameters chart reads a key records don't have

Chart `chart-memory` ("Model parameters vs research loop") reads the nested
`r.results?.model_params` at `static/app.js:360, 376, 510`. The canonical
record has **no `results` object**; the parameter count is flat
(`agent/schemas/hyperparam_tuning.py:379 model_params`). The failure is
*silent* because the wire model manufactures the missing container —
`api/models.py:81 results: ExperimentResults = Field(default_factory=…)` — so
every response carries `results.model_params: null` and the chart plots an
unbroken null line. `models.py:87` already exposes the flat `model_params`;
the JS never reads it. The chart has therefore been permanently empty.

### F-12e-UX-6 — primary endpoints are structurally blind to chain runs

The `LocalJsonDataSource` behind `/api/models*` globs exactly two shapes
(`local_json.py:58, 68-70`):

```
{root}/{model}/baseline/summary_*.json
{root}/{model}/{run}/agent/summary_{run}_agent.json
```

— the layout only `scripts/run_comparison.py` writes
(`run_comparison.py:1190-1191`). A chain writes
`{workspace}/iter_NNN/iteration_001/{model}/summary_iter_NNN.json`
(`sdsc_submission_scripts/run_one_iteration.py:513-517`; `core/resume.py:275`)
— no overlap. Only `/api/exploration/*` (`router.py:261-316`) understands
`iter_NNN`, and only when the chain workspace is an **immediate child** of
`root_data_dir` (`router.py:310-312`). Compounding: `first-run.md` tells the
user to run a chain into a free `--workspace` path and then "browse results
with the dashboard" — if that path is not under `root_data_dir`, every panel
is empty and the status dot is green (see D-2).

## 2. New findings (verified this audit)

### Correctness — a first-run can 500

- **D-1 · Trial-details table 500s on ordinary statuses.**
  `api/models.py:76` declares
  `status: Literal["success", "skipped_oom_risk", "error"]`, but the schema
  vocabulary has 13 statuses (`agent/schemas/hyperparam_tuning.py:301-331`)
  and production emits `skipped_time_risk`, `skipped_schema_violation`,
  `error_training`, `failed_mode_collapse`, …. The charts survive by
  requesting `status=success` (`app.js:328`); the trial table requests **no
  filter** (`app.js:684`), and `router.py:187` validates without try/except —
  one time-gated round turns the whole table into
  `Error: 500 Internal Server Error`.
- **D-2 · The health dot lies.** `/api/health` correctly reports
  `status="degraded", readable=false` for a bad root (`router.py:82-87`,
  `local_json.py:309-313`), but the frontend sets the dot from fetch success
  alone — `app.js:566 try { await fetchJSON('/api/health'); setHealth(true); }`
  — so a misconfigured root shows green/`connected`.
- **D-3 · `--config` governs only host/port.** `main.py:167-171` loads the
  named config, then hands uvicorn the import string `"dashboard.main:app"`
  (`main.py:178`), which re-executes `app = create_app(get_settings())`
  (`main.py:131`) against the **default** `dashboard_config.yaml`
  (`settings.py:22`, `lru_cache` at `:104-110`). The data root silently comes
  from the default path.
- **D-4 · The leaderboard endpoint 500s on exactly the case the backend was
  rewritten to handle.** `local_json.py:277-278` deliberately emits
  `rank: None` for a record with no metric identity;
  `api/models.py:148 rank: int` is required, so
  `router.py:253 LeaderboardEntry(**e)` raises. (Unreachable from the UI —
  the frontend never calls `/leaderboard` — but it is the documented endpoint.)
- **D-5 · The graceful-degradation diagnostics are dropped on the wire.**
  `metric_ranking_unavailable` / identity notes computed at
  `local_json.py:235-238` and advertised in `dashboard/README.md:126-130`
  never reach a client: `ModelOverview` (`models.py:132-139`) has no such
  fields, and `ConfigDict(extra="ignore")` (`models.py:103`) silently drops
  `metric_result`, `task_composition_fingerprint`, `gate_action` and
  `health_gate_results` from every record.

### Honesty — recorded truth the UI cannot show

- **D-6 · Health gates are invisible.** Zero occurrences of
  `health_gate|gate_action|verdict` under `dashboard/`. Records carry the full
  typed `health_gate_results` incl. `check_verdicts`
  (`agent/schemas/hyperparam_tuning.py:449, 465`); the UI erases the
  passed/failed/inapplicable/error distinction along with everything else. A
  gate-invalidated round and a low-scoring round are indistinguishable —
  while `first-run.md` forces the user to choose `--healthgate_mode` at
  launch, they cannot observe its effect here.
- **D-7 · Task identity is not shown.** No metric id, no direction, no
  composition fingerprint anywhere in `static/`; the "Denoising" wording is
  the only (wrong, for non-TIDMAD) identity signal. `denoising_score` is a
  field name baked into the wire models (`models.py:79, 151, 220`) and 7 JS
  read sites.
- **D-8 · No run-liveness or fresh/resume signal.** No "running" state, no
  last-record-age, nothing reads `run_invariants_lock.json` or
  `iter_NNN/manifest.json` (referenced only in comments,
  `router.py:269, 289, 329`). A half-finished and a committed iteration look
  identical; status rendering is binary green/red (`app.js:730, 820-821`).

### First-run polish

- **D-9 · Empty state has no guidance.** With an empty/absent config the
  server starts silently degraded (`settings.py:95` prints to the terminal
  only; default `root_data_dir=""` at `settings.py:31`) and the UI shows
  `no runs found` / `-- select run first --` (`app.js:197`, `index.html:34`)
  with no hint about `root_data_dir`.
- **D-10 · Model list frozen at boot.** `main.py:91` snapshots
  `list_models()` once inside `create_app`; new workspaces require a server
  restart.
- **D-11 · Every root subdirectory is listed as a "model"**
  (`local_json.py:123-125`) — a chain workspace under the root appears in the
  model dropdown and can never yield runs.
- **D-12 · CDN dependency.** `index.html:192` loads Plotly from
  `cdn.jsdelivr.net`; on an air-gapped host (the documented deployment is a
  remote GPU box behind an SSH tunnel) panels render and charts silently
  never draw.
- **D-13 · X-axis "research loop" is the array index of the fetched page**
  (`app.js:392`), renumbered by the `Limit` field; not a run concept.
- **D-14 · Chart 2 disagrees with itself about its own subject** — div
  `chart-memory`, internals `memYs`/`computeMemoryCurve` (`app.js:358-399`),
  label "Model parameters", caption "proxy for model size"
  (`index.html:123-125`).
- **D-15 · Dead config keys.** `default_run_name` is plumbed to the wire and
  never read by JS; `max_records_per_run` (`settings.py:57`) is read by
  nothing — the effective limit is `value="50"` in `index.html:41`.
- **D-16 · Error-handling is four different behaviours for one failure**
  (silent chart chip `app.js:333-336, 549`; red table text `app.js:757, 852`;
  a literal `error` `<option>` `app.js:238, 257, 774`; console-only
  `app.js:143-146`), and malformed JSON is swallowed as an empty run
  (`local_json.py:72-79`).
- **D-17 · Unescaped interpolation** of directory-derived names in every
  table/dropdown builder (`app.js:199, 548, 826`).

## 3. Post-12e implementation candidates, ranked

1. **Direction-aware frontend** (closes F-12e-UX-3): read
   `metric_result.direction` (already on records) or serve direction from the
   overview; derive best-curve comparator and labels from it. Smallest
   honest interim: neutral labels + API-served direction word.
2. **Chain-layout support in the primary panels** (closes F-12e-UX-6): teach
   `LocalJsonDataSource` the `iter_NNN/iteration_001/{model}` shape, or point
   the main panels at the exploration discovery path.
3. **Widen the wire `status` to the schema vocabulary + tolerant validation**
   (D-1, D-4: `rank: int | None`, add the ranking-diagnostic fields — D-5).
4. **Fix or remove the parameters chart** (F-12e-UX-4): read the flat
   `model_params` already on the wire.
5. **Honest health dot + empty-state hint** (D-2, D-9): render
   `/api/health.readable` and a one-line "configure `root_data_dir`" hint.
6. **Surface gate outcomes and task identity** (D-6, D-7): a per-round badge
   from `gate_action`, metric id + direction in the header.
7. **Vendor Plotly** (D-12) and de-alias chart 2's naming (D-14).
8. Liveness/freshness signal from record timestamps (D-8), real x-axis
   (D-13), config-key cleanup (D-15), one error surface (D-16), escaping
   (D-17).

## 4. What is already right

Worth preserving through any fix: the Step 10 P2a backend ranking semantics
(`local_json.py` refuses to rank two different metrics against each other,
`rank: null` for identity-less records, `metric_ranking_unavailable` reasons);
the read-only data-source ABC seam (`data_sources/base.py`); and
`dashboard/README.md`'s accurate endpoint/config documentation.
