# Contributing to SIDERIUS

SIDERIUS is in closed beta: the repository is shared by explicit invitation
and there is no public license yet (see the README's License section).
Contributions follow the ordinary flow — branch, commit, open a PR against
`master` — with one hard expectation: run the contributor gate before you
open the PR.

## The contributor gate: `make check`

```bash
make check
```

One command, runnable by any contributor — **no GPU, no dataset, no API
key**. The unit tier mocks every heavy subsystem (LLM calls, training,
scoring, VRAM probing) by design, so a plain laptop checkout is enough.

`make check` runs the same commands as CI's quality job
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)), in the same
cheap-first order:

| stage | command | CI step |
|---|---|---|
| `lint` | `uv run --no-sync ruff check .` | "Lint — ruff check" |
| `format-check` | `uv run --no-sync ruff format --check .` | "Lint — ruff format (check only)" |
| `typecheck` | `uv run --no-sync pyright` — or a labelled skip, see below | "Type check — pyright" |
| `test` | `uv run --no-sync pytest tests/unit/ -m "not real_run" -q` | "Unit tests — pytest" |

The recipes are guarded against drift:
`tests/unit/tools/test_contributor_gate_makefile.py` compares them against the
workflow file's actual command strings and goes red if either side changes
alone. If you change a CI command, change the [`Makefile`](Makefile) in the
same commit.

On pull requests CI may run a *selected subset* of the unit tier
(`tools/ci_selection/`, fail-closed — any doubt runs everything); master and
the nightly schedule always run the full tier. `make check` always runs the
full tier, so a green local gate is a superset of any PR selection.

### Environment: the one supported path

```bash
uv sync --group dev --frozen
```

Run that once before the first `make check`. It is exactly what CI executes
(on Python 3.12) before every gate, and the CI run is where its
reproducibility is continuously verified — `pip install`, conda, or an
unlocked `uv sync` are not certified paths. The gate itself never installs,
upgrades, or re-locks anything: recipes use `uv run --no-sync`, so a stale
environment fails visibly instead of being silently "fixed". See
[Installation](docs/getting-started/installation.md).

### Runtime bound

The unit tier dominates the wall time. One full witness run (2026-08-25, one
warm Linux workstation, venv already synced) measured **20m34s wall** for the
whole gate: ruff check + format-check in seconds, the pyright probe under a
second, and the ~13,250-test unit tier at 20m29s. Budget **~25 minutes** —
machines differ, and CI's budget for the same work is its 25-minute job
timeout.

### The pyright stage can skip — and says so

The PyPI `pyright` package wraps the Node.js implementation. On a host whose
Node runtime cannot execute it, `make check` prints a clearly labelled line —

```
SKIP typecheck: this host's toolchain cannot run pyright (…); CI owns this check — the 'uv run pyright' step in .github/workflows/ci.yml.
```

— and continues. A skip is honest, not green: CI runs pyright unconditionally
on every push and PR, so type errors are still caught before merge. If your
host has a modern Node.js, the stage runs in full locally.

### What the gate does NOT cover

`make check` is necessary, never sufficient. It does not run:

- **Real-training / GPU / real-LLM Gates** — the evidence system for changes
  touching training, inference, scoring or prompt surfaces lives in
  [`docs/gates/gate_testing_standard.md`](docs/gates/gate_testing_standard.md).
  A green unit tier says nothing about a change whose failure class needs
  real data or a real model.
- **Integration tiers** (`tests/integration/`) — pseudo-mode and real-API
  tiers are run manually/locally by design and are never in CI.
- **Real-API tests** (`-m real_run`, `--real-api-call`) — opt-in, skipped
  without keys.

### Git worktrees

Linked worktrees (`git worktree add …`) have no `.venv` of their own. Point
commands at the project's established virtual environment explicitly, or set
`UV_PROJECT_ENVIRONMENT` to that environment. Tests and entrypoint dry-runs
must still resolve source from the worktree under test; sharing an interpreter
must not silently import a different checkout.

### Before you open a PR

1. `make check` at your final head, from a clean tree.
2. Take the verdict from the log, not from a wrapper's exit code.
3. Never fix a red gate by relaxing it — no `noqa`, no rule disabling, no
   test deletion to get green; fix the code (repo rule, see `CLAUDE.md`).
4. The PR's automatic CI on the merge candidate is the canonical exact-head
   evidence; don't hand-dispatch duplicate full runs.
