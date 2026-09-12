# Your first run

**Prerequisite**: [Installation](installation.md).

This page is deliberately honest about what you can run today without a dataset,
with a dataset, and not at all yet.

---

## Level 0 — no API key, no dataset, no GPU

**Focused checkout checks are the zero-cost first contact.** They run with *no
API key at all* and verify source origin plus the shipped Quickstart manifest:

```bash
.venv/bin/python -m pytest \
  tests/unit/examples/test_quickstart_pack.py::test_composition_authority_resolves_from_this_checkout \
  tests/unit/examples/test_quickstart_pack.py::test_shipped_manifest_composes_with_the_declared_values -q
```

For broader deterministic validation, run the affected unit tests. Tests marked
`real_run` require an explicit real-mode flag and are not part of this offline
first contact.

The integration tree contains both pseudo and opt-in real tests; it is not a
uniform millisecond, credential-free command. Use the markers and each test's
instructions to choose a bounded pseudo subset:

```bash
.venv/bin/python -m pytest -m 'not real_run' tests/integration/workflows -q
```

This exercises selected deterministic workflow wiring; it is not a scientific
run or a substitute for the task package's real-data checks.

### When you do add a key

Real runs (Level 1 onward) need an LLM provider. Three are known to the
bridge — **OpenAI** (`OPENAI_API_KEY`), **Gemini** (`GEMINI_API_KEY`) and
**DeepSeek** (`DEEPSEEK_API_KEY`) — and any other OpenAI-compatible endpoint
works by passing `base_url`/`api_key` explicitly. Keys go in a `.env` file at
the repository root (see [installation](installation.md#api-keys)); the
bridge loads it automatically.

What you will see when the key is wrong, so you recognise it:

- **Missing key**: the client refuses at construction —
  `The api_key client option must be set either by passing api_key to the
  client or by setting the OPENAI_API_KEY environment variable`.
- **Invalid key**: the provider's HTTP 401 (`openai.AuthenticationError`) is
  **raised immediately, not retried** — the bridge's retry policy is explicit
  that auth and other 4xx client errors "are raised immediately — they will
  not heal on retry" (`agent/llm_bridge.py`). Only rate limits (429) and
  server errors (5xx) are retried.
- Quota exhaustion (429), by contrast, retries indefinitely by design: top up
  the balance and a long chain resumes on its own.

`.venv/bin/python scripts/diagnostics/check_agent_environment.py` checks each configured provider and
prints `<PROVIDER>_API_KEY not found in .env` or the provider's own error for
a bad one. It is an opt-in network diagnostic, not an offline checkout smoke;
its printed summary is authoritative because even a critical failure currently
exits zero. The former `env_validation/test_agent_env.py` path is retired.

## Level 1 — a dry run

If you want to see exactly what a real chain would execute, without executing it:

```bash
bash scripts/launch/run_chain.sh \
    --mode lilab \
    --workspace /path/to/your/workspace \
    --run_name first_run_v1 \
    --task_composition configs/task_composition/quickstart.yaml \
    --data_dir /path/to/workspace/quickstart_data \
    --num_iterations 1 \
    --max_rounds 1 \
    --dry-run
```

`--dry-run` walks the chain and prints the exact child commands with no side
effects. Do this before every unfamiliar configuration.

## Level 2 — a real external task

Real scientific task packages and campaign workflows live in the separate
`siderius-exp` repository. Point the same generic launcher at that repository's
manifest and workspace; no framework checkout file needs to be edited.

Start small — one iteration, one round, trial budget, a bounded scope:

```bash
bash scripts/launch/run_chain.sh \
    --mode lilab \
    --workspace /path/to/your/workspace \
    --run_name first_run_v1 \
    --task_composition /path/to/siderius-exp/tasks/example/compositions/workflow.yaml \
    --data_dir /path/to/task/data \
    --healthgate_mode blocking \
    --result_authority scientific \
    --num_iterations 1 \
    --max_rounds 1 \
    --data_scope 0-9 \
    --trial_time_budget_minutes 20
```

Notes on the flags that are not obvious:

- `--healthgate_mode` and `--result_authority` have **no defaults**. A formal
  launch without both exits `2`.
- `--data_dir` is **required** for a composed run.
- `--data_scope` bounds the work; under a partial scope, `--health_gate_files`
  must be given and be in-scope.
- Time budgets prevent a badly chosen data portion from producing a multi-hour
  round.

Omitting `--task_composition` is refused. Every supported run declares its task explicitly.

## What you will see

The run creates a workspace containing per-node output records, an effective
health config, an invariants lock, and the generated model plugins. Browse
results with the dashboard:

```bash
python src/dashboard/main.py     # http://localhost:8000
```

## Level 3 — real task packages

Real task packages are maintained outside this repository. Each package owns
its manifest, plugins, Health science, data instructions, and workflow
settings. It calls the same `run_chain.sh` entrypoint shown above and writes all
generated modules and run artifacts beneath its declared workspace.

The framework repository intentionally does not ship Oxford-IIIT Pet, DAVIS,
TIDMAD, Cancer Gene Identification, or any other scientific task as a default.
Use the task package documentation in the consumer repository for its exact
launch command and data requirements.

## When something refuses

Most first-run problems are deliberate refusals, not bugs. The table in
[operating a run](../guides/operating-a-run.md#failures-and-refusals) maps each
one to its cause.

---

## Next

- [What SIDERIUS is](../concepts/overview.md)
- [Operating a run](../guides/operating-a-run.md)
- [Define your own task](../guides/define-a-task.md)
