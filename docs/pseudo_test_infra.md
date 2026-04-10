# Pseudo-Full-Loop Test Infrastructure — Design

**Status**: design — implementation underway on `feat/pseudo-full-loop-infra` branch.

## 0. The problem

SIDERIUS today has two test classes:

- **Unit tests** (`tests/unit/`): mocked LLM, no GPU, no real data, run in CI on every commit. Fast and narrow. They cover one function or one class at a time.
- **Integration tests** (`tests/integration/nodes/`, `tests/integration/protocols/`, `tests/integration/workflows/`): real LLM API calls, real subprocesses, real GPU. Slow, expensive, and gated behind `pytest.mark.real_run` so they never run in CI.

There is no middle tier. The orchestration glue — prompt assembly, record building, persistence, the wiring between agent code and its dependencies — is exercised either narrowly (one function at a time) or only by burning real API quota and GPU time. As soon as we touch a node's orchestration logic (e.g. the just-landed Phase A `regime_scores` wiring), we get to choose between writing five separate unit tests that each cover a tiny slice OR running a 5-minute real-API integration test that costs Gemini quota every time.

We need a third tier: **fast, broad, mocked end-to-end tests that exercise the entire orchestration of a node or workflow without touching the network or the GPU**.

## 1. The concept: pseudo-full-loop

> **Pseudo-full-loop test**: a test that exercises the *entire orchestration* of a node or workflow end-to-end, but with **every external dependency mocked**:
> - LLM API calls go through a `RecordingLLMBridge` that returns canned responses and records every prompt sent.
> - Subprocess execution (training, inference, scoring) goes through a `RecordingSandbox` that returns canned `train_status` / `score_res` payloads.
>
> The test asserts on three things at once: (a) the prompts the LLM would have received, (b) the records assembled by the orchestration logic, (c) the persistence path. Runs in milliseconds, no GPU, no API key, no real data.

The principle that makes this work: **every external dependency is mockable**. The system has exactly two classes of external dependency (LLM and subprocess execution), and both must be hidden behind injection points so a test can swap them for recording fakes.

This is not a testing tactic — it is a load-bearing design decision. It changes how nodes are constructed (constructor dependency injection), how integration tests are written (dual-mode by default), and what it means for the codebase to be "well-tested" (orchestration coverage in CI, not just function coverage).

## 2. The dual-mode rule

**Every integration test (Tier 1, Tier 2, Tier 3) is written ONCE and runs in either of two modes**:

| Mode | LLM | Subprocess execution | Speed | Selected by | When it runs |
|---|---|---|---|---|---|
| **Pseudo (default)** | `RecordingLLMBridge` returns canned responses | `RecordingSandbox` returns canned results | milliseconds | (default behavior) | Every commit, in CI |
| **Real** | `LLMBridge` makes real API calls | `TidmadSandbox` runs real subprocesses | minutes – hours | `pytest --real-api-call` (or `-m real_run`) | On demand by humans only |

The same `def test_*(...)` body runs in both modes. The mode is selected by a fixture that swaps the factory functions. The test author writes one test; pytest runs it in pseudo mode by default and in real mode when explicitly requested.

This eliminates the false dichotomy between "fast unit test of a tiny function" and "slow real-API integration test that burns quota every commit". Every commit gets full orchestration coverage at zero quota cost.

## 3. The four-tier test taxonomy (revised)

| Tier | What's mocked | What's real | Speed | Catches |
|---|---|---|---|---|
| **unit** | Everything except the function under test | one function | μs | Function correctness |
| **pseudo_full_loop** | LLM + subprocess execution | Pure orchestration logic (record assembly, prompt rendering, persistence) | ms | Orchestration glue, prompt content, record assembly |
| **integration Tier 1/2/3** (real mode) | Nothing | Everything | minutes – hours | Real LLM behavior, real data, real GPU |

The pseudo_full_loop tier is the missing middle: as fast as unit tests, as broad as integration tests. Most contributors will only ever interact with the unit and pseudo_full_loop tiers.

## 4. Architectural prerequisites

Three things must change in the codebase before pseudo_full_loop tests can be written.

### 4A. Dependency injection at every node constructor

Today every node constructs its own `LLMBridge` and `TidmadSandbox` inside `run()`. Tests cannot swap these. The fix is **optional constructor parameters** that accept factory callables, defaulting to the real classes:

```python
class HyperparamTuningAgent:
    def __init__(
        self,
        bridge_factory: Callable[..., LLMBridge] = LLMBridge,
        sandbox_factory: Callable[..., TidmadSandbox] = TidmadSandbox,
    ):
        self._bridge_factory = bridge_factory
        self._sandbox_factory = sandbox_factory

    def run(self, agent_input):
        bridge = self._bridge_factory(provider=..., model_id=...)
        sandbox = self._sandbox_factory(...)
        ...
```

Production code passes nothing — gets real `LLMBridge` and `TidmadSandbox` like today. Tests pass `RecordingLLMBridge` and `RecordingSandbox`. Backward compatible by construction: every existing call site continues to work without modification.

This pattern applies to **every node** (`ml_hyperparameter_tune_agent`, `ml_model_proposal_agent`, `ml_model_implementor`, `ml_code_validator_agent`, `result_interpretation_agent`). This PR retrofits only `HyperparamTuningAgent` as proof; subsequent PRs retrofit the others incrementally as their phases of the V2 design land.

### 4B. Recording test doubles

Two new files in `tests/helpers/`:

```
tests/helpers/
├── __init__.py
├── recording_llm_bridge.py   # RecordingLLMBridge
└── recording_sandbox.py      # RecordingSandbox
```

#### `RecordingLLMBridge`

A drop-in replacement for `LLMBridge` that returns predefined responses and records every call. Minimal — does not parse, does not transform, does not synthesize. The predefined responses are dicts shaped exactly like the parsed output of a real `LLMBridge.generate()` / `reflect()` call.

```python
class RecordingLLMBridge:
    """Test double for LLMBridge. Returns predefined responses, records every call.

    Predefined responses are dicts (the same shape the real bridge returns AFTER
    parsing the LLM's JSON). Per-method FIFO queue: register one or more responses,
    each call pops the next.
    """

    def __init__(self, responses: dict | None = None, **kwargs):
        # **kwargs accepts (and silently ignores) the real LLMBridge constructor
        # parameters (provider, model_id, reflect_provider, reflect_model_id, ...)
        # so the agent can construct it via self._bridge_factory(**real_kwargs)
        # without any test-side translation.
        self._queues: dict[str, list] = {}
        for method, value in (responses or {}).items():
            self._queues[method] = list(value) if isinstance(value, list) else [value]
        self.calls: list[tuple] = []

    def generate(self, system_prompt: str, user_prompt: str) -> dict:
        self.calls.append(("generate", system_prompt, user_prompt))
        return self._pop("generate")

    def reflect(self, exp_id, hypothesis, results, context) -> dict:
        self.calls.append(("reflect", exp_id, hypothesis, results, context))
        return self._pop("reflect")

    def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append(("generate_text", system_prompt, user_prompt))
        return self._pop("generate_text")

    def _pop(self, method: str):
        if not self._queues.get(method):
            raise RuntimeError(
                f"RecordingLLMBridge: no canned response left for {method!r}. "
                f"Did the test forget to register one?"
            )
        return self._queues[method].pop(0)

    @classmethod
    def for_agent(cls, agent_name: str) -> "RecordingLLMBridge":
        """Build a bridge pre-loaded with the canned outputs for a specific agent.
        Loads from tests/pseudo_data/api_call_outputs/{agent_name}/*.json — one
        file per LLM method (generate.json, reflect.json, ...)."""
        responses = _load_pseudo_data("api_call_outputs", agent_name)
        return cls(responses=responses)
```

**~30 LOC. No helper methods, no parsing dispatch, no factories. Tests inspect `bridge.calls` directly.**

#### `RecordingSandbox`

A drop-in replacement for `TidmadSandbox` that **mimics the real sandbox's persistence behavior as faithfully as possible** — real directories on disk under `tmp_path`, real JSON files written, real `save_record` semantics. The only thing skipped is the actual subprocess execution (training, inference, scoring): those return canned dicts directly instead of running.

```python
class RecordingSandbox:
    """Test double for TidmadSandbox. Mimics the real sandbox's persistence
    behavior (real directories, real files written) but skips subprocess
    execution: training/inference/scoring return predefined dicts instead.
    """

    def __init__(
        self,
        base_dir: str,            # real tmp_path passed by the test
        run_name: str = "test",
        canned: dict | None = None,
        **kwargs,                 # accept and ignore extras for drop-in compat
    ):
        self.base_dir = base_dir
        self.run_name = run_name
        self.dirs = {
            "configs": os.path.join(base_dir, "configs", run_name),
            "models":  os.path.join(base_dir, "cached_models"),
            "records": os.path.join(base_dir, "records"),
            "data":    os.path.join(base_dir, "data"),
        }
        for path in self.dirs.values():
            os.makedirs(path, exist_ok=True)

        # Stub anchor map so the tuner agent's load_anchor_map() works.
        # Minimal valid shape; the canned execute_scoring result is what
        # actually drives the test, not the real anchor data.
        stub = {"anchors": {0: {0: 1.0}}, "s_max": 1.0}
        with open(os.path.join(self.dirs["data"], "segment_anchors.json"), "w") as f:
            json.dump(stub, f)

        # Canned outputs FIFO queue per method
        self._queues: dict[str, list] = {}
        for method, value in (canned or {}).items():
            self._queues[method] = list(value) if isinstance(value, list) else [value]

        # Public attributes for test assertions
        self.calls: list[tuple] = []
        self.saved_records: list[dict] = []

    def execute_training(self, exp_id, run_name, model_type, m_cfg, t_cfg, l_cfg, **kwargs):
        self.calls.append(("execute_training", exp_id, model_type, m_cfg, t_cfg, l_cfg))
        result = self._pop("execute_training")
        # Mirror the real persistence: write the canned result to the same
        # disk path the real subprocess would have written, so any code that
        # reads it back works exactly like real mode.
        result_path = os.path.join(
            self.dirs["records"], run_name,
            f"experiment_results_{model_type}_{exp_id}.json",
        )
        os.makedirs(os.path.dirname(result_path), exist_ok=True)
        with open(result_path, "w") as f:
            json.dump(result.get("results", {}), f)
        return result

    def execute_inference(self, exp_id, run_name, model_type, m_cfg, l_cfg, **kwargs):
        self.calls.append(("execute_inference", exp_id, model_type))
        return self._pop("execute_inference")
        # NOTE: real inference produces .h5 denoised files. We skip those —
        # scoring is also canned, so nothing reads them. If a future test
        # specifically wants to exercise the .h5 path, it can write a stub.

    def execute_scoring(self, exp_id, run_name, model_type, **kwargs):
        self.calls.append(("execute_scoring", exp_id, model_type))
        result = self._pop("execute_scoring")
        score_path = os.path.join(
            self.dirs["records"], run_name,
            f"score_results_{model_type}_{exp_id}.json",
        )
        os.makedirs(os.path.dirname(score_path), exist_ok=True)
        with open(score_path, "w") as f:
            json.dump(result.get("results", {}), f)
        return result

    def save_record(self, record: dict):
        # In-memory list for fast test assertions
        self.saved_records.append(record)
        # Also write to disk like the real sandbox does (append to summary file)
        summary_path = os.path.join(self.base_dir, f"summary_{self.run_name}.json")
        existing = []
        if os.path.exists(summary_path):
            with open(summary_path) as f:
                existing = json.load(f)
        existing.append(record)
        with open(summary_path, "w") as f:
            json.dump(existing, f)

    def _pop(self, method: str):
        if not self._queues.get(method):
            raise RuntimeError(
                f"RecordingSandbox: no canned response left for {method!r}. "
                f"Did the test forget to register one?"
            )
        return self._queues[method].pop(0)

    @classmethod
    def for_model(cls, model_type: str, base_dir: str, **kwargs) -> "RecordingSandbox":
        """Build a sandbox pre-loaded with canned outputs for a specific built-in
        model. Loads from tests/pseudo_data/train_outputs/{model_type}/*.json —
        one file per execute method (execute_training.json, execute_inference.json,
        execute_scoring.json)."""
        canned = _load_pseudo_data("train_outputs", model_type)
        return cls(base_dir=base_dir, canned=canned, **kwargs)
```

**~80 LOC. Real directories under tmp_path, real disk persistence, in-memory `saved_records` for fast assertions.**

#### Pseudo data layout

```
tests/pseudo_data/
├── api_call_outputs/
│   ├── ml_hyperparameter_tune_agent/
│   │   ├── generate.json                     # canned ExperimentPlan dict
│   │   └── reflect.json                      # canned reflection dict
│   ├── ml_model_proposal_agent/              # added by Phase B follow-up PR
│   │   └── generate.json
│   ├── ml_model_implementor/                 # added by follow-up PR
│   │   └── generate.json
│   ├── ml_code_validator_agent/              # added by follow-up PR
│   │   └── generate.json
│   └── result_interpretation_agent/          # added by follow-up PR
│       ├── per_model_summary.json
│       └── synthesis.json
└── train_outputs/
    ├── punet/                                 # v1 — only model in this PR
    │   ├── execute_training.json
    │   ├── execute_inference.json
    │   └── execute_scoring.json
    └── (wavenet/, fcnet/, gated_fno/, ...)    # added incrementally as needed
```

**v1 scope for this PR**: only `ml_hyperparameter_tune_agent/` under `api_call_outputs/`, only `punet/` under `train_outputs/`. Other agents/models added by follow-up PRs as their consumers come online.

**Helper for loading**:

```python
# tests/helpers/_pseudo_data.py
PSEUDO_DATA_ROOT = pathlib.Path(__file__).parent.parent / "pseudo_data"

def _load_pseudo_data(category: str, name: str) -> dict[str, dict]:
    """Load all *.json files under tests/pseudo_data/{category}/{name}/.
    Returns {filename_without_ext: parsed_json_dict}."""
    target_dir = PSEUDO_DATA_ROOT / category / name
    if not target_dir.is_dir():
        raise FileNotFoundError(
            f"No pseudo_data directory at {target_dir}. "
            f"Add canned outputs there before using for_agent/for_model."
        )
    out = {}
    for json_file in sorted(target_dir.glob("*.json")):
        with open(json_file) as f:
            out[json_file.stem] = json.load(f)
    return out
```

**~15 LOC.**

#### How a test uses all of this

```python
def test_one_round_tuner(tmp_path):
    bridge = RecordingLLMBridge.for_agent("ml_hyperparameter_tune_agent")
    sandbox = RecordingSandbox.for_model("punet", base_dir=str(tmp_path))

    agent = HyperparamTuningAgent(
        bridge_factory=lambda **kw: bridge,
        sandbox_factory=lambda **kw: sandbox,
    )
    output = agent.run(test_input)

    # Inspect via in-memory list (fast)
    assert sandbox.saved_records[0]["regime_scores"]["low_freq_kHz"] == pytest.approx(0.5)

    # OR inspect via disk (also works because we mirror real persistence)
    summary_path = os.path.join(tmp_path, "summary_test.json")
    assert os.path.exists(summary_path)

    # Inspect prompt content
    assert "REGIME SCORES" in bridge.calls[0][1]  # planner system prompt
```

### ⚠️ PROJECT INVARIANT — read this before adding or editing any pseudo data

> **Pseudo data depends on real schemas. By design.**
>
> The dual-mode test design has exactly one assumption that makes the entire thing work: **the predefined responses in `tests/pseudo_data/` must always match the real API output schema**. Pseudo mode does not parse, does not transform, does not synthesize — it returns the registered dict verbatim. So if the real `LLMBridge.generate()` starts returning a slightly different shape (e.g. a renamed field, a new required key, a tightened Pydantic constraint), the corresponding pseudo data file must change in the same commit.
>
> Concretely, this means:
>
> 1. **A schema change is a two-file change.** Updating `agent/schemas/hyperparam_tuning.py` (or any other schema consumed by the pseudo data) requires updating every relevant `tests/pseudo_data/.../*.json` file in the same PR. The reviewer should reject any schema change that doesn't.
> 2. **Pseudo tests are NOT for detecting LLM API problems.** That is what real-mode tests (gated behind `--real-api-call`) exist for. Don't try to use pseudo mode to catch upstream API quirks; you will fool yourself.
> 3. **Predefined responses are post-parse, not raw wire format.** The recording bridge does not strip markdown fences or call `json.loads`. Test authors register the parsed dict shape that the real bridge would have produced after parsing.
> 4. **The schema-pseudo-data sync is a project invariant, not an opportunistic check.** No CI test enforces it (we deliberately did not write one — that would be circular). Contributors must enforce it manually as part of any schema change. The README at `tests/pseudo_data/README.md` repeats this so anyone navigating to add new canned data sees it first.
>
> The trade-off is intentional. Building automatic schema validation into the recording fakes (e.g. running `Schema.model_validate(canned_response)` at registration time) would catch sync drift early but would also (a) re-test the production schema's own validators, (b) require importing every schema into the test helpers, and (c) make the recording fakes opinionated about a specific schema layer they shouldn't know about. We chose simplicity + project discipline over enforced fidelity.

### 4C. Fixture-based mode switching (locked design: orthogonal axes)

A pytest fixture decides which factories to inject based on a CLI flag, and the existing `pytest.mark.real_run` marker is preserved for a separate, orthogonal purpose.

**Two independent axes**:

| Concept | Mechanism | What it means |
|---|---|---|
| **Test category — dual-mode** | `pytest.mark.dual_mode` | "This test supports BOTH pseudo and real modes. By default (no flag) it runs in pseudo mode; with `--real-api-call` it runs in real mode against the real API." Almost every integration test in the future will be marked this way. |
| **Test category — real-only** | `pytest.mark.real_run` | "This test ONLY works in real mode — it has no pseudo equivalent (e.g. it asserts on actual LLM output structure that no canned response could meaningfully validate)." Reserved for the rare case where pseudo mode genuinely cannot validate the thing. Skipped by default; needs both `-m real_run` AND `--real-api-call`. |
| **Execution mode** | `--real-api-call` CLI flag | "When pytest runs today, use the real `LLMBridge` / `TidmadSandbox` instead of the recording fakes." Pseudo mode is the default; real mode requires explicit opt-in. Affects `dual_mode` tests (switches them from pseudo to real) and is required for `real_run` tests to actually execute. |

These axes are independent. A test can be:

- **Dual-mode** (marked `dual_mode`): runs in pseudo mode by default; runs in real mode if `--real-api-call` is passed. **This is the recommended pattern for almost every integration test.** The marker is a structural label that says "this test supports both modes" — it makes the dual nature explicit and discoverable, and distinguishes the test from unmarked unit tests and from real-only `real_run` tests.
- **Real-only** (marked `real_run`): skipped by default; runs only when both the `-m real_run` selector AND the `--real-api-call` flag are passed. Reserved for tests that have no canned-response equivalent.
- **Unmarked**: regular unit tests under `tests/unit/`. Run in CI on every commit. Mocked at the function level, not at the LLM/sandbox boundary.

**Combination matrix**:

| Command | Dual-mode tests (`dual_mode`) | Real-only tests (`real_run`) | Unit tests (no marker) |
|---|---|---|---|
| `pytest tests/` | run in **pseudo** mode | skipped | run normally |
| `pytest tests/ --real-api-call` | run in **real** mode | skipped (still need `-m`) | run normally |
| `pytest tests/ -m real_run` | skipped (different marker) | skipped (need flag too) | skipped (no marker) |
| `pytest tests/ -m real_run --real-api-call` | skipped (different marker) | run in **real** mode | skipped (no marker) |
| `pytest tests/ -m dual_mode` | run in **pseudo** mode (selected) | skipped | skipped |
| `pytest tests/ -m dual_mode --real-api-call` | run in **real** mode (selected) | skipped | skipped |

**Why this design**:

- **One concept does one thing**. The marker tells you *what kind of test* it is. The flag tells pytest *how to execute it today*. They never mean the same thing.
- **Default is safe**. Without any flag or marker, you get pseudo mode for everything that supports it. No accidental quota burn.
- **Composable**. A future test could be both `real_run`-marked and dual-mode-able if we ever need a third mode (e.g. record-and-replay) — the flag/marker combination handles it without redesign.
- **Backward compatible**. The existing `real_run` marker keeps its meaning. Tests that use it today don't need to change; they just become real-only by default until someone migrates them.
- **Discoverable**. `pytest --help` shows the new flag.

**Rejected alternative**: reusing `-m real_run` as the mode selector. It's shorter to type but overloads the marker with two meanings (category AND mode), forcing every future test author to disambiguate. Trades long-term clarity for short-term keystrokes.

Fixture skeleton:

```python
# tests/conftest.py
def pytest_addoption(parser):
    parser.addoption(
        "--real-api-call",
        action="store_true",
        default=False,
        help="Run integration tests in real mode (real LLM API + real subprocess). "
             "Requires API keys and GPU. Default: pseudo mode (recording fakes).",
    )

@pytest.fixture
def tuner_factories(request):
    if request.config.getoption("--real-api-call"):
        from agent.llm_bridge import LLMBridge
        from core.sandbox_executor import TidmadSandbox
        return {"bridge_factory": LLMBridge, "sandbox_factory": TidmadSandbox}
    else:
        from tests.helpers.recording_llm_bridge import RecordingLLMBridge
        from tests.helpers.recording_sandbox import RecordingSandbox
        return {"bridge_factory": RecordingLLMBridge, "sandbox_factory": RecordingSandbox}
```

Tests that need to assert on prompt content (only meaningful in pseudo mode) skip themselves in real mode via `request.config.getoption("--real-api-call")`. Tests that exercise real-LLM-only behavior (e.g. validating that the LLM's natural output meets the schema) skip themselves in pseudo mode the same way.

## 5. Implementation plan for this PR

The PR is intentionally narrow: it builds the infrastructure and proves it works on ONE node, leaving the other four nodes for follow-up PRs.

### Files (touched or created)

| Path | Status | Purpose |
|---|---|---|
| `docs/pseudo_test_infra.md` | new | This design doc |
| `docs/architecture.md` | modified | New section on the pseudo_full_loop tier; updated test taxonomy table |
| `tests/helpers/__init__.py` | new | Package marker |
| `tests/helpers/recording_llm_bridge.py` | new | `RecordingLLMBridge` test double |
| `tests/helpers/recording_sandbox.py` | new | `RecordingSandbox` test double |
| `tests/helpers/test_recording_doubles.py` | new | Unit tests for the test doubles themselves |
| `tests/conftest.py` | new or modified | `pytest_addoption` for `--real-api-call`; `tuner_factories` fixture |
| `nodes/ml_hyperparameter_tune_agent.py` | modified | Add optional `bridge_factory` / `sandbox_factory` constructor params (DI). Backward compatible. |
| `tests/integration/nodes/test_tune_ml_hyperparam_agent.py` | modified | Refactor ONE existing test (`test_punet_gemini[loss_cfg0]`) to dual-mode as proof. Other tests untouched. |

### Step-by-step

The phases below are independent enough that any subset is committable.

- ☑ **S.1** Created `tests/helpers/__init__.py` (empty package marker) and `tests/helpers/_pseudo_data.py` with the `load_pseudo_data(category, name)` helper. ~55 LOC including docstrings; 1 small function. Smoke-checked: `PSEUDO_DATA_ROOT` resolves to `tests/pseudo_data`, and `FileNotFoundError` fires with a clear message when the requested directory doesn't exist.
- ☑ **S.2** Wrote `tests/helpers/recording_llm_bridge.py` with the `RecordingLLMBridge` class as specified in §4B. Constructor accepts `responses` dict and `**kwargs` (drop-in compat — silently swallows real-bridge constructor params); exposes `calls` list for direct test inspection; raises `RuntimeError` with a diagnostic message on queue exhaustion; classmethod `for_agent(name)` loads from `tests/pseudo_data/api_call_outputs/{name}/`. Implements `generate`, `reflect`, `generate_text`, `tool_call`. ~140 LOC including docstrings; ~35 LOC of actual logic. Smoke-checked: drop-in init with real-bridge kwargs works; predefined responses returned correctly; `calls` list records call order; queue exhaustion raises clearly; FIFO list-form queue works.
- ☑ **S.3** Wrote `tests/helpers/recording_sandbox.py` with the `RecordingSandbox` class as specified in §4B. Constructor accepts `base_dir` (real `tmp_path`), `run_name`, `canned`, and `**kwargs`. Creates real directories under `base_dir`; writes a stub `segment_anchors.json` (minimal valid shape) so the tuner agent's anchor map check passes; mirrors disk persistence in `execute_training` / `execute_scoring` (writes real result JSONs to the same path the real subprocess would have used) and `save_record` (writes to a real `summary_{run_name}.json` AND to the in-memory `saved_records` list); classmethod `for_model(model_type, base_dir, run_name)` loads from `tests/pseudo_data/train_outputs/{model_type}/`. ~230 LOC including docstrings; ~95 LOC of actual logic. Smoke-checked: drop-in init; real directories created; stub anchor map written; `execute_training` returns canned dict and writes file to disk; `execute_scoring` same; `save_record` writes summary file and appends correctly across multiple calls; queue exhaustion raises clearly; `calls` list records every attempted invocation (including those that exhausted the queue, since `_pop` raises AFTER `calls.append`).

**Validation after S.1-S.3** (before continuing to S.4):
- `uv run pytest tests/unit/ -q` → 775 passed (unchanged from before; no regressions from adding helpers).
- `uv run pytest tests/helpers/ --collect-only -q` → 0 tests collected (correct — no `test_*.py` files there yet; S.4 adds the first one).
- All three helper modules import cleanly under standard `PYTHONPATH`.
- ☐ **S.4** Write `tests/helpers/test_recording_fakes.py` — small smoke tests for the recording fakes themselves so we trust the infrastructure. Cover: register-and-pop, queue exhaustion raises, `calls` list ordering, `for_agent`/`for_model` load JSONs from the right paths, real directories are created under `tmp_path`, `save_record` writes a JSON file to disk. ~50 LOC. (See open question E if you'd rather skip.)
- ☐ **S.5** Create the v1 pseudo data:
  - `tests/pseudo_data/api_call_outputs/ml_hyperparameter_tune_agent/generate.json` — a valid `ExperimentPlan`-shaped dict (small punet config).
  - `tests/pseudo_data/api_call_outputs/ml_hyperparameter_tune_agent/reflect.json` — a valid reflection dict (`conclusion`, `key_factor`, `discovery`, `memory_update`).
  - `tests/pseudo_data/train_outputs/punet/execute_training.json` — `{"status": "success", "results": {"final_loss": 0.5, "loss_history": [...], "model_params": 12345}}`.
  - `tests/pseudo_data/train_outputs/punet/execute_inference.json` — `{"status": "success", "results": {}}` (inference produces .h5 files in real mode, nothing meaningful to return).
  - `tests/pseudo_data/train_outputs/punet/execute_scoring.json` — `{"status": "success", "results": {"denoising_score": 0.69, "file_vector": [0.5, 0.5, 0.5, 0.5, 0.5, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9]}}` — chosen so the resulting `regime_scores` are easy to verify by hand.
- ☐ **S.6** Add `pytest_addoption` for `--real-api-call` to `tests/conftest.py` (creating it if absent). Add a fixture `tuner_factories(request, tmp_path)` that returns `{"bridge_factory": ..., "sandbox_factory": ...}` based on the flag.
- ☐ **S.7** Add constructor DI to `HyperparamTuningAgent`: optional `bridge_factory` and `sandbox_factory` parameters defaulting to `LLMBridge` and `TidmadSandbox`. Replace internal `LLMBridge(...)` and `TidmadSandbox(...)` calls with `self._bridge_factory(...)` and `self._sandbox_factory(...)`. **No behavioral change in production**: when factories aren't passed, the agent constructs the real classes exactly as before.
- ☐ **S.8** Refactor `tests/integration/nodes/test_tune_ml_hyperparam_agent.py::TestRealRunGemini::test_punet_gemini[loss_cfg0]` to dual-mode. Use the `tuner_factories` fixture. **Replace** the `@pytest.mark.real_run` marker with a new `@pytest.mark.dual_mode` marker on this one test (registered in `tests/conftest.py` via `pytest_configure`). The `dual_mode` marker is a structural label that says "this test supports both pseudo and real modes" — distinct from `real_run` (real-only) and from unmarked unit tests. Default behavior: dual_mode tests run in pseudo mode in CI; they switch to real mode when `--real-api-call` is passed. In pseudo mode, the recording fakes are pre-loaded via `for_agent` / `for_model`; assertions are about prompt content + saved record structure + recorded subprocess calls. In real mode, the same test runs end-to-end against the real API as it does today.
- ☐ **S.9** Run the full unit suite plus the new pseudo-mode test in CI configuration (no `--real-api-call`). All existing tests continue to pass. The newly-refactored test passes in pseudo mode in milliseconds.
- ☐ **S.10** Update `docs/architecture.md`: new "Pseudo-full-loop tests" section after the existing Testing Strategy section, new principle 10 in Core Principles, updated taxonomy table.
- ☐ **S.11** Update `CLAUDE.md` if needed (one-line addition under Coding Standards) referencing the new tier.

### Cross-step verification gates

- After S.1–S.4: `uv run pytest tests/helpers/ -q` passes (the recording-fake smoke tests).
- After S.5: the JSON files exist and parse cleanly. `python -c "import json; json.load(open('tests/pseudo_data/api_call_outputs/ml_hyperparameter_tune_agent/generate.json'))"` runs without error.
- After S.7: `uv run pytest tests/unit/ -q` still passes (DI added but production path unchanged).
- After S.8: `uv run pytest tests/integration/nodes/test_tune_ml_hyperparam_agent.py::TestRealRunGemini::test_punet_gemini -q` (pseudo mode, no flag) passes in milliseconds.
- After S.8: `uv run pytest tests/integration/nodes/test_tune_ml_hyperparam_agent.py::TestRealRunGemini::test_punet_gemini -q --real-api-call` (real mode) still passes — verifying the refactor didn't break the existing real-mode behavior.
- After S.9: `uv run pytest tests/unit/ tests/helpers/ -q` is fully green.

### Out of scope for this PR (deferred to follow-ups)

Each item below is a **PR-size scoping decision**, not a technical limitation. The infrastructure built in this PR works for any node in the graph; the deferrals just keep this PR's blast radius small enough to review confidently. The table below makes the trade-off explicit so a future contributor (or the same contributor on a different day) can decide whether to pull any item back into scope.

| Item | Approx. LOC | Risk | Recommendation | Why deferred |
|---|---|---|---|---|
| **(1) DI on the other 4 nodes** (`ml_model_proposal_agent`, `ml_model_implementor`, `ml_code_validator_agent`, `result_interpretation_agent`) | medium (~800, ~200/node) | low | defer | Each node has its own subtleties about *how* it uses the bridge and sandbox. `ml_model_implementor`, for example, runs subprocesses for `pytest` execution and plugin loading — we don't yet know whether `RecordingSandbox` covers those calls or whether they need their own injection points. Validating the pattern on one node first surfaces unknowns before they multiply across five. Each subsequent node is its own small follow-up PR. |
| **(2) Refactor the other ~10 integration test methods in `test_tune_ml_hyperparam_agent.py` to dual-mode** | medium (~300) | low | defer to immediate follow-up | Mostly mechanical (copy-paste of the dual-mode pattern across loss/model parametrizations), but adds bulk that obscures the infra changes. Best as a separate "migrate test_tune_ml_hyperparam_agent.py to dual-mode" PR landing right after this one. The unmigrated tests still run in real mode exactly as today — they're not broken, just single-mode. |
| **(3) Tier 2 (protocols) and Tier 3 (workflows) dual-mode** | high (unknown unknowns) | **high** | **strongly defer** | Tier 2 needs the fixture to thread factories into TWO nodes per test (e.g. `result_interpretation_agent` and `ml_model_proposal_agent` for the `interp_to_propose` protocol). Tier 3 runs an entire workflow that internally constructs many bridges and sandboxes — the fixture has to inject factories deep into workflow code. These are **new design problems**, not extensions of the Tier 1 pattern. We should validate Tier 1 works before extending to harder cases. |
| **(4) Phase A's `pseudo_full_loop` test** (sub-task A.8 from `docs/adaptive_new_model_proposer.md`) | small (~100) | low | **defensible to pull in** | The most concrete validation of the new infra on the thing we actually built it for. The downside is conceptual — bundling "build the infra" with "use the infra to test Phase A" mixes ownership boundaries. The upside is that #4 is the first thing we'd write right after this PR merges anyway, and it's TINY. This is the most defensible item to pull into scope if we want a single end-to-end story. |

**Plan (locked)**: defer all four. Land this PR with the infra + one proof-of-concept dual-mode test, then immediately follow with PRs #1, #2, #4 (in some order). Item #3 waits until Tier 1 dual-mode is battle-tested.

This keeps each PR clear, concise, and independently reviewable. The follow-ups are sequenced for compounding leverage: first #1 (DI on the other 4 nodes) so the infra has multiple consumers, then #2 (migrate the rest of the same test file) so we have a dense pseudo-mode harness for the tuner, then #4 (Phase A's pseudo_full_loop test) which validates the regime_scores wiring on top of the now-mature infra.

## 6. Why this design is minimalist

In keeping with the V2 design philosophy ("minimalist architecture, maximalist reasoning"), this PR adds the smallest possible amount of new infrastructure to unlock the new tier:

- **No new test framework**. Reuses pytest, fixtures, CLI options.
- **No new schema**. The recording fakes implement the existing interfaces of `LLMBridge` and `TidmadSandbox`.
- **No new node**. Just constructor parameters on existing nodes.
- **No new directory hierarchy**. `tests/helpers/` is one new directory; the existing `tests/unit/` and `tests/integration/` keep their meaning.
- **No new file convention**. The same integration test file holds both modes; the fixture decides which path runs.
- **No breaking changes**. Every existing test, every existing CLI command, every existing call site continues to work without modification. Migration is opt-in, file by file.

The PR's blast radius is exactly: one new helpers directory, one new fixture, one node gains two optional constructor params, one existing test gains a pseudo path. Everything else is documentation.

## 7. Open questions and decisions

### Resolved

- ☑ **Mode selector** (§4C). **Orthogonal axes**: `--real-api-call` flag for execution mode + existing `pytest.mark.real_run` marker for test category. Two independent concepts; pseudo is the default.
- ☑ **Recording fakes location**. `tests/helpers/` — most conventional, doesn't overload pytest's "fixtures" terminology.
- ☑ **Pseudo data location and structure**. `tests/pseudo_data/{api_call_outputs,train_outputs}/{agent_or_model}/{method}.json`. JSON files, one per LLM/subprocess call type. v1 ships only `ml_hyperparameter_tune_agent/` and `punet/`; other agents/models added incrementally as their consumers come online.
- ☑ **Canned response shape**. Predefined responses are plain Python dicts shaped exactly like the post-parse output of a real `LLMBridge.generate()` / `reflect()` or a real `TidmadSandbox.execute_*()`. No parsing dispatch, no string mode, no factories. The schema fidelity is maintained as a project invariant: pseudo data and real API response shapes are kept in sync as part of any schema change.
- ☑ **Filesystem fidelity for `RecordingSandbox`**. Real directories under `tmp_path`, real disk persistence (`save_record` writes a real `summary_*.json`; `execute_training` writes a real `experiment_results_*.json` to mirror the subprocess output). Stub `segment_anchors.json` written by `__init__` so the tuner's anchor map check passes.
- ☑ **Constructor signature mismatch**. `RecordingLLMBridge.__init__(self, responses=None, **kwargs)` and `RecordingSandbox.__init__(self, base_dir, run_name="test", canned=None, **kwargs)`. The `**kwargs` swallow real-bridge / real-sandbox constructor parameters so the agent code can construct them via the factory without test-side translation.
- ☑ **Pseudo mode is NOT a substitute for real-mode tests for LLM-output validation**. The pseudo tier covers everything except "did the real LLM actually produce a valid response". Real-mode tests are still required for that one concern. Test authors should NOT try to use pseudo mode to detect API quirks or schema drift — that's what `--real-api-call` is for.

### Newly resolved

- ☑ **Multi-call per method (forward-looking)**. **Distinct files per sub-call**. When Phase B's proposal agent introduces two `generate(...)` calls per run, the canned data lives in `generate_reasoning.json` and `generate_architecture.json` (or similar) under `pseudo_data/api_call_outputs/ml_model_proposal_agent/`. Each file is one logical sub-call. The recording bridge's `for_agent()` classmethod will need a small update at that point to map sub-call names → which response to pop next, but that's a Phase-B follow-up concern. v1 stays simple: one method = one file.
- ☑ **Refactored test marker**. **Replaced, not removed**: `@pytest.mark.real_run` on `test_punet_gemini[loss_cfg0]` becomes `@pytest.mark.dual_mode`. The new marker is registered in `tests/conftest.py` via `pytest_configure`. This makes the dual nature explicit and discoverable, distinguishes the test from unmarked unit tests, and keeps the matrix in §4C unambiguous. The other 10 tests in the same file keep `real_run` until they're migrated (each migration replaces `real_run` with `dual_mode` and adds the canned-data wiring).
- ☑ **Unit tests for the recording fakes themselves (S.4)**. **Yes**, write them. ~50 LOC of smoke tests covering register-and-pop, queue exhaustion, calls list ordering, classmethod loading, real directory creation under tmp_path, save_record disk persistence. The fakes are load-bearing infrastructure for every future pseudo test.
- ☑ **Tuner's sub-skill call sites**. **Grep performed; no audit needed.** All five sub-skill wrappers under `agent/skills/` (`training_skill`, `inference_skill`, `denoising_score_skill`, `evaluate_resource_skill`, `check_config_format_skill`) take `sandbox` as their first positional argument from the agent and forward method calls onto it. None construct their own `TidmadSandbox`. None construct their own `LLMBridge` (the singleton invariant test enforces this). The agent at `nodes/ml_hyperparameter_tune_agent.py` is the single point of construction for both. **DI at the agent constructor is therefore sufficient** — every sub-skill transparently uses whatever sandbox the agent passes in. No follow-up needed for sub-skill audits.
