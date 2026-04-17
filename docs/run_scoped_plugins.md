# Run-scoped plugin directories

**Status**: in progress (started 2026-04-17)

## Progress

| Phase | Status | Commit | Notes |
|-------|--------|--------|-------|
| 1 — plugin_loader env var support | ✅ done | `634a12e` | `_resolve_plugin_dirs` + `SIDERIUS_PLUGIN_DIRS`; 9 new unit tests |
| 2 — tuner sandbox sets env var | ✅ done | (pending commit) | `TidmadSandbox.plugin_dir` + env wiring; 6 new unit tests |
| 3 — seed plugin copy | ⬜ pending | — | `seed_plugin_path` schema field, AST validation, copy at run start |
| 4 — implementor writes into run dir | ⬜ pending | — | workflow populates `ImplementorInput.plugin_dir` with run-scoped path |
| 5 — deprecate global dir | ⬜ out of scope (future) | — | drop `AGENT_GENERATED_DIR` fallback; requires full caller audit |

## Problem

`ml_models/plugin_loader.py` scans a single global directory,
`agent_generated/models/`, at import time. Every process that imports
`ml_models.models_sandbox` therefore picks up every plugin file ever produced
by any past run. This causes:

- **Cross-run pollution** — a tuner run for model A sees config classes and
  `nn.Module` classes for unrelated models B, C, D from past runs.
- **Slower startup** — every plugin file is `exec`'d at import time.
- **Fragile bootstrap** — one broken plugin file from a prior run can poison
  the loader for every future process (silently filtered by `_load_plugin`'s
  try/except, so the regression is invisible until something downstream is
  missing).
- **No run audit trail** — there is no way to ask "which plugins did run X
  actually use?" after the fact, because all plugins share one directory.

What a run actually needs: its **seed model** (built-in *or* a specific
plugin file) plus whatever **new plugins it proposed during the run**.
Nothing else.

## Design

### Directory layout

Legacy plugins stay at the repo root (read-only back-compat). Per-run
plugins live under the **workspace**, alongside other per-run outputs
(`configs/<run_name>/`, `records/<run_name>/`). Two workspaces never
collide; tests that point `workspace` at `tmp_path` are automatically
self-contained.

```
<repo>/agent_generated/
└── models/                        # legacy global dir — preserved for back-compat
    └── <old>.py

<workspace>/plugins/
└── <run_name>/
    ├── <seed_plugin>.py           # copied in at run start (if seed is a plugin)
    └── <proposed_plugin>.py       # written by implementor during the run
```

### Plugin resolution

Introduce a single env var:

```
SIDERIUS_PLUGIN_DIRS   # os.pathsep-separated list of directories to scan
```

`ml_models/plugin_loader.py` gets a new resolver:

```python
def _resolve_plugin_dirs() -> list[str]:
    """Return the list of directories to scan for plugins.

    Priority:
      1. SIDERIUS_PLUGIN_DIRS env var (os.pathsep-separated). Per-run mode.
      2. [AGENT_GENERATED_DIR] — legacy global dir. Back-compat default.
    """
    env = os.environ.get("SIDERIUS_PLUGIN_DIRS", "").strip()
    if env:
        return [p for p in env.split(os.pathsep) if p.strip()]
    return [AGENT_GENERATED_DIR]
```

`extend_registries` iterates the resolved list. The module-level
`AGENT_GENERATED_DIR` constant stays — it is the fallback, and existing
tests that override it continue to work unchanged.

### Who sets what

| Actor | What it does |
|-------|--------------|
| Tuner node (`nodes/ml_hyperparameter_tune_agent.py`) | Constructs a `TidmadSandbox(run_name=...)`. The sandbox creates `<workspace>/plugins/<run_name>/` and exposes it as `self.plugin_dir`; it also sets `SIDERIUS_PLUGIN_DIRS=self.plugin_dir` in the env it passes to every subprocess it spawns. Seed plugin copy (Phase 3) happens inside the tuner before the first training call. |
| Training subprocess (`execute_tools/train_engine_sandbox.py`) | No change. Inherits env var from `subprocess.run(env=...)`. `plugin_loader` picks it up automatically. |
| Implementor node (`nodes/ml_model_implementor.py`) | Receives `plugin_dir` via `ImplementorInput` (already exists — `default="agent_generated/models"`). The caller — workflow or orchestrator — populates it with the run-scoped dir. |
| Workflow (`workflows/model_exploration.py`) | When assembling `ImplementorInput`, passes the run-scoped `plugin_dir`. When copying validated plugins, copies to the run-scoped dir. |
| Description resolver (`ml_models/model_descriptions.py`, `nodes/proposal_helpers.py`) | Gets a second lookup path: `agent_generated/runs/<run_name>/models/<model_type>/description.md`, with the legacy global path as fallback. |

### Seed plugin handling

Two supported modes, chosen by the tuner input's existing `model_type` field:

- **Built-in seed** (`model_type ∈ {"punet", "fcnet", ...}`): nothing to do.
  The built-in is already in `MODEL_REGISTRY` — no plugin file needed.
- **Plugin seed** (`model_type` is a plugin's `PLUGIN_MODEL_TYPE`):
  tuner input gets a new optional field `seed_plugin_path: Optional[str]`.
  On run start, the tuner copies the file into
  `agent_generated/runs/<run_name>/models/`. Validation: the file's
  `PLUGIN_MODEL_TYPE` must equal `model_type` (read via AST or a safe
  import-in-isolation). If mismatch → fail loudly before any training.

This keeps the loader ignorant of "seed vs proposed" — both are just
files in the run dir.

### Backward compatibility contract

- **When `SIDERIUS_PLUGIN_DIRS` is unset** (every current caller): behavior
  is identical to today. `AGENT_GENERATED_DIR` is scanned, all existing
  plugins load. Every existing test and script keeps working.
- **When `SIDERIUS_PLUGIN_DIRS` is set**: only the listed dirs are scanned.
  The tuner uses this for the training subprocess; nothing else needs to
  opt in.
- **Global `agent_generated/models/`** is **not deprecated** in this
  change. It remains writable and readable. A future change may migrate
  older plugins into a per-run layout and retire the global dir — that is
  out of scope here.
- **Why workspace-rooted, not repo-rooted?** The initial design placed
  per-run dirs under `<repo>/agent_generated/runs/...` for consistency
  with the legacy global dir. This caused test pollution (every
  `TidmadSandbox(workspace=tmp_path)` leaked a real dir into the repo)
  and conflated "agent-generated artifacts that ship with the repo" with
  "per-run outputs that don't". Workspace-rooting removes both problems.

## Phased migration

Each phase ships independently, green tests at every boundary.

### Phase 1 — plugin_loader env var support

- Add `_resolve_plugin_dirs()`.
- `extend_registries` iterates the resolved list; preserves current return
  shape (flat list of loaded `model_type` strings).
- Update `.gitignore` to cover `agent_generated/runs/**/*.py`.
- **Tests**:
  - Unit: env var unset → scans `AGENT_GENERATED_DIR` (existing behavior).
  - Unit: env var set to one dir → scans only that dir.
  - Unit: env var set to two dirs → scans both; plugins from both appear.
  - Unit: env var set, `AGENT_GENERATED_DIR` does not exist → no fallback,
    no errors (explicit mode).
  - Subprocess: bootstrap regression (existing `TestBootstrapRegistryMirror`)
    still passes — the mirror fix is orthogonal to this change.
- **Callers changed**: none. Back-compat preserved.

### Phase 2 — tuner sets env var for training subprocess

- Tuner creates `agent_generated/runs/<run_name>/models/` at run start.
- Tuner adds `SIDERIUS_PLUGIN_DIRS=<that dir>` to the env it passes to
  `execute_tools/train_engine_sandbox.py`.
- **No change** to the legacy outer-process bootstrap — it still scans
  the global dir at `import ml_models.models_sandbox` time. (Outer process
  pollution is addressed in Phase 5.)
- **Tests**:
  - Unit: tuner writes env var; mock subprocess captures it.
  - Integration (pseudo-full-loop): run completes with empty
    `agent_generated/models/` (legacy global dir), because the training
    subprocess only needs the run dir.

### Phase 3 — seed plugin copy

- Add `seed_plugin_path: Optional[str]` to `HyperparamTuningInput`.
- Validate: if set, the file exists and its `PLUGIN_MODEL_TYPE` equals
  `model_type`. Use AST (`ast.parse` + walk `Assign` nodes) — do *not*
  exec the file at validation time, because that would pollute
  `sys.modules`.
- At run start, copy the file into the run dir. Abort run if copy fails.
- **Tests**:
  - Unit: valid seed plugin → copied, registry loads it.
  - Unit: mismatched `PLUGIN_MODEL_TYPE` → validation error, no copy.
  - Unit: missing file → validation error.

### Phase 4 — implementor writes into run dir

- Workflow and any orchestrator that calls the implementor populates
  `ImplementorInput.plugin_dir` with
  `agent_generated/runs/<run_name>/models`.
- `ImplementorInput.plugin_dir`'s default stays `agent_generated/models`
  for back-compat: anyone invoking the implementor directly without a
  run context gets the legacy behavior.
- **Tests**:
  - Unit: workflow constructs `ImplementorInput` with run-scoped dir.
  - Integration: a fresh run writes its proposed plugin only into
    `agent_generated/runs/<run_name>/models`.

### Phase 5 (future, out of scope) — deprecate global dir

- Drop the `AGENT_GENERATED_DIR` fallback.
- Require `SIDERIUS_PLUGIN_DIRS` (or a programmatic equivalent) for every
  caller that wants plugins.
- Migration tool to move any leftover files in `agent_generated/models/`
  into per-run dirs (or archive them).
- This is a separate change and requires an audit of every caller. Do
  not bundle it with phases 1–4.

## Test plan (consolidated)

| Tier | File | Covers |
|------|------|--------|
| Unit | `tests/unit/ml_models/test_plugin_loader.py` | `_resolve_plugin_dirs` precedence, multi-dir scan, empty-env fallback |
| Unit (existing) | `tests/unit/ml_models/test_plugin_loader.py::TestBootstrapRegistryMirror` | regression guard on bootstrap mirror (unchanged) |
| Unit | `tests/unit/agent/tune_ml_hyperparam_agent/test_seed_plugin_validation.py` (new) | seed plugin path validation, mismatch error, missing file error |
| Unit | `tests/unit/workflows/test_model_exploration.py` | workflow threads run-scoped `plugin_dir` into `ImplementorInput` |
| Integration (pseudo) | `tests/integration/workflows/test_model_exploration.py` | full loop with empty global dir — proves per-run isolation |

## Open questions

1. **Run name collisions**: two runs with the same `run_name` would share
   a plugin dir. Current tuner allows this (it appends to existing
   records). Proposal: refuse to start if the run dir exists and is
   non-empty, unless a `--resume` flag is passed. Discuss before Phase 2.
2. **Disk cleanup**: run dirs accumulate. Propose a retention policy
   (e.g., keep last N runs) separately; not blocking.
3. **Cross-run plugin reuse**: e.g. run B wants to use run A's proposal
   as its seed. The Phase 3 `seed_plugin_path` design handles this — the
   path can point at another run's dir. Verify the validation flow
   works across run boundaries.
