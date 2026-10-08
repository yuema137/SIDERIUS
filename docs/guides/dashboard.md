# Browsing results with the dashboard

**Answers**: how to point the dashboard at your results, what it can and cannot
show today, and why a page might be empty.

The dashboard is a read-only FastAPI + Plotly browser over the JSON records a
run writes. It never touches the experiment pipeline. Endpoint and
configuration reference: [`dashboard/README.md`](../../src/dashboard/dashboard-contract.md).

---

## Start it

```bash
cp dashboard_config.example.yaml dashboard_config.yaml   # once; then edit
.venv/bin/python src/dashboard/main.py                       # http://localhost:8000
```

Set one key in `dashboard_config.yaml`:

```yaml
data_source:
  local:
    root_data_dir: /path/to/your/results   # the directory ABOVE your runs
```

Two pages are served: the charts at `/`, and a Swagger API explorer at
`/api/docs` — the API is often the more honest of the two (see below).

For a run on a remote machine, tunnel it: `ssh -L 8000:localhost:8000 <host>`.

Three practical rules, each the result of a verified quirk:

- **Edit `dashboard_config.yaml` at the repository root** — do not rely on
  `--config` for the data root. The `--config` flag currently affects only
  host/port/log-level; the data source is rebuilt from the default config path
  when the server module is re-imported by uvicorn.
- **Restart after new runs appear.** The model list is read once at server
  start; a workspace created afterwards is invisible until restart.
- **The browser needs the internet once.** Plotly loads from a CDN; on an
  air-gapped host the page renders its panels but every chart silently stays
  blank.

## What it understands today

The main panels (series charts, trial table) discover runs in the
**comparison layout** written by `scripts/run_comparison.py`:

```
{root_data_dir}/{model}/baseline/summary_baseline_{model}.json
{root_data_dir}/{model}/{run_name}/agent/summary_{run_name}_agent.json
```

A **chain workspace** (`run_chain.sh`) is a different shape, and only the
*exploration* panel reads it — and only when the chain workspace directory sits
**directly under** `root_data_dir`. So:

> Running `run_chain.sh --workspace /data/my_chain_v1`?
> Set `root_data_dir: /data` — the *parent* — and use the exploration panel.

⚠ This split is a known limitation, not a layout choice you made wrong. The
chain layout is the production layout, and making the primary panels
understand it is a recorded post-PR-12e candidate — see the
[dashboard UX audit](../agent-reference/dashboard_ux_audit.md).

## When the page is empty

In likelihood order:

| check | detail |
|---|---|
| does `dashboard_config.yaml` exist? | without it the server starts silently with an empty data root and shows "no runs found" |
| is `root_data_dir` the *parent* of your workspace? | chain workspaces must be immediate children; comparison layouts must match the shapes above |
| did the run exist before the server started? | restart the server — the model list is frozen at boot |
| are the charts blank but dropdowns populated? | the Plotly CDN was unreachable |
| still nothing? | hit `/api/health` in the API explorer — it reports whether the configured root is actually readable |

⚠ **The green status dot does not mean your data was found.** It only means
the server answered; the frontend does not read the health payload's degraded
state. `/api/health` is the truthful check.

## Reading it honestly

Things the UI shows that deserve a caveat, and things it does not show at all:

- **Chart labels say "Denoising score (higher = better)" regardless of your
  task.** The *API* (leaderboard, model overview) reads each record's declared
  metric identity and direction; the *charts* still hardcode
  higher-is-better and the TIDMAD label. On a lower-is-better task the
  chart's "cumulative best" line is wrong — trust the API ordering, not the
  chart. ⚠ Known defect, recorded in the
  [UX audit](../agent-reference/dashboard_ux_audit.md).
- **The "Model parameters" chart is currently always empty** — it reads a key
  the records do not carry. ⚠ Same audit.
- **Health-gate results are not rendered anywhere.** A round invalidated by a
  blocking gate and a round that merely scored low look identical here. Read
  the tuner's records in the workspace for gate verdicts — see
  [workspaces and resume](workspaces-and-resume.md).
- **The task's identity is not shown.** Records carry the metric id and
  composition fingerprint; the UI does not display them yet.
- **The x-axis "research loop" is the record's position in the fetched page**,
  not a run concept — changing the `Limit` field renumbers it.

None of these affects what was *recorded* — the workspace JSONs and the API
carry the full truth; the charts are a convenience layer that predates the
multi-task framework. The complete defect list with file-level evidence and
post-PR-12e fix candidates lives in the
[dashboard UX audit](../agent-reference/dashboard_ux_audit.md).

---

## Next

- [`dashboard/README.md`](../../src/dashboard/dashboard-contract.md) — endpoints, configuration, tests
- [Workspaces and resume](workspaces-and-resume.md) — reading records directly
- [Troubleshooting](troubleshooting.md)
