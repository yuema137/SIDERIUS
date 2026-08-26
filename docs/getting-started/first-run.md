# Your first run

**Prerequisite**: [Installation](installation.md).

This page is deliberately honest about what you can run today without a dataset,
with a dataset, and not at all yet.

---

## Level 0 — no API key, no dataset, no GPU

**The full unit suite is the zero-cost first contact.** It runs with *no API
key at all* — every LLM is mocked, nothing touches the network, and CI runs
the same suite (`-m "not real_run"`) with no secrets configured:

```bash
uv run pytest tests/unit/ -q
```

That claim is enforced, not aspirational: the handful of tests that *do* need
real API keys or real data are marked `real_run` and are **skipped at
collection** unless you explicitly pass a real-mode flag
(`--real-api-call` / `--real-llm` / `--real-training`). A plain `pytest`
invocation cannot spend money by accident.

The integration suite runs the full node orchestration against **predefined**
LLM and subprocess responses — the complete plan → train → score → reflect wiring
in milliseconds, still no API key, no GPU:

```bash
uv run pytest tests/integration/ -q
```

This is the fastest way to see the shape of the system. It is not a scientific
run.

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

`python env_validation/test_agent_env.py` checks each configured provider and
prints `<PROVIDER>_API_KEY not found in .env` or the provider's own error for
a bad one.

## Level 1 — a dry run

If you want to see exactly what a real chain would execute, without executing it:

```bash
bash sdsc_submission_scripts/run_chain.sh \
    --mode lilab \
    --workspace /path/to/your/workspace \
    --run_name first_run_v1 \
    --task_composition configs/task_composition/tidmad.yaml \
    --data_dir /path/to/tidmad/data \
    --num_iterations 1 \
    --max_rounds 1 \
    --dry-run
```

`--dry-run` walks the chain and prints the exact child commands with no side
effects. Do this before every unfamiliar configuration.

## Level 2 — a real TIDMAD run

TIDMAD is the flagship task and the deepest-exercised path through the
production chain. You need the raw `.h5` files staged at `tidmad_data_dir`
(~50 GB) and a CUDA GPU.

Start small — one iteration, one round, trial budget, a bounded scope:

```bash
bash sdsc_submission_scripts/run_chain.sh \
    --mode lilab \
    --workspace /path/to/your/workspace \
    --run_name first_run_v1 \
    --task_composition configs/task_composition/tidmad.yaml \
    --data_dir /path/to/tidmad/data \
    --healthgate_mode blocking \
    --result_authority scientific \
    --num_iterations 1 \
    --max_rounds 1 \
    --data_scope 4-9 \
    --health_gate_files 4,7,9 \
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

Omitting `--task_composition` runs the ⚠ legacy un-composed path. It works, but
it is not the path to learn.

## What you will see

The run creates a workspace containing per-node output records, an effective
health config, an invariants lock, and the generated model plugins. Browse
results with the dashboard:

```bash
python dashboard/main.py     # http://localhost:8000
```

## Level 3 — the contrast example tasks

✅ **Available.** The Oxford-IIIT Pet and DAVIS example packs run through the
same composed production chain as TIDMAD (PR-12d landed the task-neutral
subprocess path; both packs are at declared maturity **L4**).

Each pack ships exactly one documented run command — a thin `quickstart.sh`
that supplies the pack's composition manifest and bounded defaults, then execs
the normal chain launcher. For Pets:

```bash
# one-time: fetch the dataset to a machine-local directory outside the repo
.venv/bin/python -m tools.example_packs.fetch_oxford_iiit_pet \
    --dest /path/outside/repo --extract

bash examples/oxford_iiit_pet/quickstart.sh \
    --workspace /path/to/your/workspace \
    --data_dir /path/outside/repo/images
```

DAVIS is the same shape (`examples/davis_future_prediction/quickstart.sh`).
Both are equivalent to calling `run_chain.sh` yourself with
`--task_composition configs/task_composition/pets.yaml` (or `davis.yaml`) —
the shipped manifests point into the packs; nothing about them is
special-cased. Extra arguments pass straight through to the chain launcher,
so `--dry-run` works here too.

See [supported tasks and current maturity](../concepts/supported-tasks.md) for
what those runs do and do not demonstrate (single-round composed witnesses;
health gates do not yet fire on the composed path), and each pack's
`README.md` / `STATUS.md` for the full journey.

## When something refuses

Most first-run problems are deliberate refusals, not bugs. The table in
[operating a run](../guides/operating-a-run.md#failures-and-refusals) maps each
one to its cause.

---

## Next

- [What SIDERIUS is](../concepts/overview.md)
- [Operating a run](../guides/operating-a-run.md)
- [Define your own task](../guides/define-a-task.md)
