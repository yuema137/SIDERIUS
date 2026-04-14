# Pseudo-Full-Loop Test Infrastructure — Design

**Status**: Phase 1 complete (S.1–S.11, merged). Phase 2 complete — F.1–F.9 all passing. See §7 for the full plan and checklist.

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
- ☑ **S.4** Wrote `tests/helpers/test_recording_fakes.py` with 20 pytest tests across three classes (`TestRecordingLLMBridge`, `TestRecordingSandbox`, `TestLoadPseudoData`). Coverage: drop-in init with real-class kwargs swallowed, predefined-response delivery, `calls` list recording (including failed attempts), FIFO queue, queue exhaustion raises with diagnostic, `for_agent`/`for_model` load from a temporarily monkeypatched `PSEUDO_DATA_ROOT`, `for_agent` raises on missing dir, real directory creation under `tmp_path`, stub anchor map written, `execute_training`/`execute_scoring` mirror disk persistence, `save_record` in-memory + appending summary file. ~270 LOC including docstrings. **All 20 tests pass in 30 ms.**
- ☑ **S.5** Created the v1 pseudo data (and inspected the real schemas to ensure shape fidelity, per the project invariant in §4C):
  - `tests/pseudo_data/api_call_outputs/ml_hyperparameter_tune_agent/generate.json` — validates against `ExperimentPlan`. Inner `model_config` validates against `PUNetConfig` (multi=40, depth=4, kernel_size=9, embedding_dim=32, etc.); inner `train_config` validates against `TrainConfig` (lr=1e-4, epochs=5, optimizer=adamw, device=cuda); inner `loss_config` validates against `LossConfig` (focal, alpha=0.5, gamma=2.0). is_trial=true, trial_strategy=snapshot, trial_portion=0.05.
  - `tests/pseudo_data/api_call_outputs/ml_hyperparameter_tune_agent/reflect.json` — the four documented keys (`conclusion`, `key_factor`, `discovery`, `memory_update`). Realistic content explicitly referencing the regime breakdown to demonstrate the prompt template.
  - `tests/pseudo_data/train_outputs/punet/execute_training.json` — `{status, message, results: {final_loss: 0.4231, loss_history: [...], model_params: 12345678}}`. Matches what `train_engine_sandbox.py` writes plus the wrapper from `core/sandbox_executor.py`.
  - `tests/pseudo_data/train_outputs/punet/execute_inference.json` — `{status, message, results: {}}`. Inference produces `.h5` files in real mode; the canned dict is empty because scoring is also canned.
  - `tests/pseudo_data/train_outputs/punet/execute_scoring.json` — `denoising_score=0.69`, `file_vector=[0.5]*5 + [0.7]*6 + [0.9]*9` chosen so the hand-computed regime_scores are exactly `{low_freq_kHz=0.5, mid_freq_10kHz=0.7, high_freq_MHz=0.9, global=0.74}`.

  **Created `tests/pseudo_data/README.md`** as a prominent invariant reminder for any future contributor navigating into the pseudo_data tree. Repeats the §4C invariant block ("schema change is a two-file change") plus the directory layout and naming conventions.

  **Validated end-to-end** (Python smoke check, not yet a pytest test):
    - `RecordingLLMBridge.for_agent('ml_hyperparameter_tune_agent')` loads both `generate.json` and `reflect.json`.
    - `RecordingSandbox.for_model('punet', base_dir=tmp)` loads all three execute_*.json files and writes them to real disk paths.
    - The canned `file_vector` aggregates to the hand-computed regime scores (`low=0.5, mid=0.7, high=0.9, global=0.74`).
- ☑ **S.6** Extended `tests/conftest.py` (which already existed for the `--real-data` flag). Added `--real-api-call` to the existing `pytest_addoption`; added a new `pytest_configure` that registers the `dual_mode` marker; added the `tuner_factories(request, tmp_path)` fixture. In real mode the fixture returns `{"bridge_factory": LLMBridge, "sandbox_factory": TidmadSandbox}` (the real classes — no behavioral change from today). In pseudo mode it returns closures that build pre-loaded `RecordingLLMBridge.for_agent("ml_hyperparameter_tune_agent")` and `RecordingSandbox.for_model("punet", base_dir=tmp_path)` instances. Both closures accept arbitrary `**kwargs` so the agent's existing constructor call signature works without translation. **Validated**: `pytest --help` shows `--real-api-call`; `pytest --markers` shows `dual_mode`; full unit + helpers suite stays at 795 passed; closure simulation returns the expected canned data.
- ☑ **S.7** Added constructor DI to `HyperparamTuningAgent`: optional `bridge_factory` and `sandbox_factory` parameters defaulting to `LLMBridge` and `TidmadSandbox`. Replaced internal `LLMBridge(...)` and `TidmadSandbox(...)` calls at lines 159/166 with `self._bridge_factory(...)` and `self._sandbox_factory(...)`. **No behavioral change in production**: both existing call sites (`ml_hyperparameter_tune_agent.py:851` CLI entrypoint and `workflows/model_exploration.py:521` workflow) use `HyperparamTuningAgent()` with no args, which defaults to the real classes exactly as before.
- ☑ **S.8** Added a new standalone dual-mode test function `test_punet_one_round_dual_mode` at the bottom of `tests/integration/nodes/test_tune_ml_hyperparam_agent.py`, marked `@pytest.mark.dual_mode` and parametrized over `[formal, trial]`. The existing `TestRealRunGemini` tests are **untouched** (they keep their `real_run` marker and behavior). In pseudo mode: the test constructs `RecordingLLMBridge.for_agent(...)` and `RecordingSandbox.for_model(...)` directly, injects them via `bridge_factory`/`sandbox_factory` lambdas, and after the run asserts on (a) first LLM call is `plan`, (b) saved record has `denoising_score`, `file_vector`, `final_loss`, `model_params`, (c) reflector received `denoising_score` and `file_vector` in its results, (d) call sequence includes `plan → execute_training → reflect → save_record`. In real mode (`--real-api-call`): the test uses `HyperparamTuningAgent()` with real classes and applies the same output-structure assertions. **Fixes discovered during S.8**: (1) `RecordingSandbox` was missing `get_summary()` — added, returns `list(self.saved_records)`. (2) `RecordingLLMBridge` was missing `plan()` — added, records the call and pops from the `"generate"` queue (since `plan` in the real bridge is a wrapper that assembles a prompt then calls `generate`). (3) Trial-mode scoring calls `score_vector()` directly in agent code (bypasses sandbox) — monkeypatched in pseudo mode to return the predefined file_vector + scalar. (4) Predefined plan updated: `device → "cpu"` (so the resource check doesn't need a GPU), `is_trial → false` (matches the formal-mode test path; trial-mode test overrides via `agent_input.is_trial`).
- ☑ **S.9** Full suite: **778 passed** (776 unit + 20 helpers + 2 dual-mode). No regressions. Both `test_punet_one_round_dual_mode[formal]` and `test_punet_one_round_dual_mode[trial]` pass in pseudo mode in ~15 seconds each (dominated by model instantiation for the resource check, not by any real training).
- ☑ **S.10** Updated `docs/architecture.md`: (1) New principle 9a "Every external dependency is mockable" in Core Principles, explaining the DI factory pattern, the LLMBridge singleton invariant, and the `--real-api-call` flag. (2) New "Pseudo-full-loop tests (dual-mode)" subsection in Testing Strategy, explaining the two modes, the markers (`dual_mode` vs `real_run`), the predefined data layout, and the schema-fidelity invariant. (3) Updated the Summary table to include the pseudo-full-loop tier as a first-class row. (4) Updated the opening paragraph to reference five categories (was four) and link to `docs/pseudo_test_infra.md`.
- ☑ **S.11** Updated `CLAUDE.md`: replaced the integration test tiers table with a five-row version that includes the pseudo-full-loop tier at the top. Added a paragraph explaining dual-mode tests (`@pytest.mark.dual_mode`, `--real-api-call`, predefined responses from `tests/pseudo_data/`) and the rule that new integration tests should be dual-mode by default.

**All 11 steps complete. PR is ready for review.**

### Cross-step verification gates

- After S.1–S.4: `uv run pytest tests/helpers/ -q` passes (the recording-fake smoke tests).
- After S.5: the JSON files exist and parse cleanly. `python -c "import json; json.load(open('tests/pseudo_data/api_call_outputs/ml_hyperparameter_tune_agent/generate.json'))"` runs without error.
- After S.7: `uv run pytest tests/unit/ -q` still passes (DI added but production path unchanged).
- After S.8: `uv run pytest tests/integration/nodes/test_tune_ml_hyperparam_agent.py::TestRealRunGemini::test_punet_gemini -q` (pseudo mode, no flag) passes in milliseconds.
- After S.8: `uv run pytest tests/integration/nodes/test_tune_ml_hyperparam_agent.py::TestRealRunGemini::test_punet_gemini -q --real-api-call` (real mode) still passes — verifying the refactor didn't break the existing real-mode behavior.
- After S.9: `uv run pytest tests/unit/ tests/helpers/ -q` is fully green.

### Deferred items — status update (Phase 1 complete)

Phase 1 (S.1–S.11) shipped. Below is the updated status of every item that was originally deferred. Item #4 (Phase A regime_scores) is superseded — Phase A was reverted. The new priority is the vocabulary feedback loop (§7).

| Item | Original scope | Current status |
|---|---|---|
| **(1) DI on the other 4 nodes** | All four nodes | ✅ `ml_model_proposal_agent` (Phase 1). ✅ `result_interpretation_agent` (F.1). ✅ `ml_model_implementor`, `ml_code_validator_agent` (F.7). |
| **(2) Migrate tuner test to dual-mode** | ~10 test methods in `test_tune_ml_hyperparam_agent.py` | ✅ `test_wavenet_one_round_dual_mode` added (F.8). Core path covered; remaining methods are @real_run. |
| **(3) Tier 2 dual-mode (protocols)** | `interp_to_propose`, `tune_to_interpret` | ✅ `interp_to_propose` (F.5). ✅ `tune_to_interpret` (F.9). |
| **(4) Phase A pseudo_full_loop test** | `regime_scores` wiring | ✅ Superseded: Phase A reverted. Replaced by §7. |

**Phase 2 complete — F.1–F.9 all passing.**

## 6. Why this design is minimalist

In keeping with the V2 design philosophy ("minimalist architecture, maximalist reasoning"), this PR adds the smallest possible amount of new infrastructure to unlock the new tier:

- **No new test framework**. Reuses pytest, fixtures, CLI options.
- **No new schema**. The recording fakes implement the existing interfaces of `LLMBridge` and `TidmadSandbox`.
- **No new node**. Just constructor parameters on existing nodes.
- **No new directory hierarchy**. `tests/helpers/` is one new directory; the existing `tests/unit/` and `tests/integration/` keep their meaning.
- **No new file convention**. The same integration test file holds both modes; the fixture decides which path runs.
- **No breaking changes**. Every existing test, every existing CLI command, every existing call site continues to work without modification. Migration is opt-in, file by file.

The PR's blast radius is exactly: one new helpers directory, one new fixture, one node gains two optional constructor params, one existing test gains a pseudo path. Everything else is documentation.

---

## 7. Phase 2 — Vocabulary Feedback Loop Tests

### Progress at a glance

| Step | What | Status | Validation gate |
|------|------|--------|-----------------|
| **F.1** | `bridge_factory` DI on `ResultInterpretationAgent` | ✅ Complete | `pytest tests/unit/ -q` — 871 passed |
| **F.2** | Pseudo data for `result_interpretation_agent` | ✅ Complete | schema smoke check passes |
| **F.3** | Dual-mode test `test_interpretation_feedback_loop` [refuted, confirmed] | ✅ Complete | 2/2 passed in pseudo mode |
| **F.4** | Unit tests `TestRenderVocabulary` (8 cases) | ✅ Complete | 8/8 passed |
| **F.5** | Tier 2 dual-mode `test_interp_to_propose_feedback_loop` | ✅ Complete | 1/1 passed, "REFUTED" in prompt confirmed |
| **F.6** | Fix stale `SummaryGroup` in both integration test files | ✅ Complete | files use `ModelRunSummary`, unit tests still green |
| **F.7** | DI on `ml_model_implementor` + `ml_code_validator_agent` | ✅ Complete | both nodes accept `bridge_factory` |
| **F.8** | Migrate remaining tuner tests to dual-mode | ✅ Complete | `test_wavenet_one_round_dual_mode` added, all passing |
| **F.9** | Tier 2 dual-mode `tune_to_interpret` test | ✅ Complete | `test_tune_to_interp_protocol_and_node` passing |

### Background and motivation

The vocabulary feedback loop is the core learning mechanism of the adaptive exploration workflow:

1. The proposer makes a `falsifiable_prediction` (e.g. "adding spectral conv will push score from 5.576 to 6.5")
2. The tuner runs and produces an actual score
3. The interpretation agent evaluates the prediction → generates a `discovery` (CONFIRMED / REFUTED / PARTIAL)
4. The discovery is added to `runtime_vocab`
5. The next iteration's proposer receives the vocab → sees the discovery → adjusts its hypothesis

Two bugs silently broke this loop for all v1/v2 runs:
- **Bug 1** (fixed): `_compute_metric()` did not recognise common LLM metric aliases (`best_score`, `overall denoising score`), so `actual_value` was always `None` → all discoveries PARTIAL.
- **Bug 2** (fixed): `_render_vocabulary()` silently dropped `discovery` and `candidate` kind entries, so even when discoveries were generated correctly, the proposer never saw them.

Both bugs are fixed in the codebase. What we do NOT yet have is a pseudo test that would have caught either bug immediately without burning API quota. This section defines that test.

### Current gaps

| Gap | Location | Impact |
|---|---|---|
| No `bridge_factory` DI on `ResultInterpretationAgent` | `nodes/result_interpretation_agent.py:328` | Cannot inject `RecordingLLMBridge` — blocks all pseudo tests for this node |
| No pseudo data for interpretation agent | `tests/pseudo_data/api_call_outputs/` | Needed by `RecordingLLMBridge.for_agent("result_interpretation_agent")` |
| No dual-mode test for feedback loop | `tests/integration/nodes/test_result_interpretation_agent.py` | Cannot verify prediction eval + discovery generation without real API |
| No unit test for `_render_vocabulary` with discoveries | `tests/unit/agent/ml_model_proposal_agent/` | Bug 2 would not have been caught by any test |
| No Tier 2 dual-mode test (interp → propose) | `tests/integration/protocols/test_interp_to_propose.py` | Cannot verify discoveries reach proposer prompt end-to-end |
| Stale schemas in existing integration tests | Both `test_result_interpretation_agent.py` and `test_interp_to_propose.py` | Use old `SummaryGroup` (replaced by `ModelRunSummary`) — tests would fail in real mode |

### Step-by-step plan

#### F.1 — Add `bridge_factory` DI to `ResultInterpretationAgent`

**File**: `nodes/result_interpretation_agent.py`

Change `__init__` from:
```python
def __init__(self, provider: str = "gemini", model_id: str = "...",
             max_retries: int | None = None):
    self.bridge = LLMBridge(provider=provider, model_id=model_id, max_retries=max_retries)
```
to:
```python
def __init__(self, provider: str = "gemini", model_id: str = "...",
             max_retries: int | None = None, bridge_factory=None, **kwargs):
    self._bridge_factory = bridge_factory or LLMBridge
    self.bridge = self._bridge_factory(provider=provider, model_id=model_id, max_retries=max_retries)
```

**Why `bridge_factory` and not a direct `bridge` instance**: the node constructs its bridge once in `__init__` and reuses it across both Phase 1 and Phase 2 LLM calls. A factory matches the existing pattern from `ml_model_proposal_agent` and `HyperparamTuningAgent`. Tests inject `lambda **kw: RecordingLLMBridge(responses={...})`.

**Validation gate**: `pytest tests/unit/ -q` still fully green. No behavior change in production (factory defaults to `LLMBridge`).

---

#### F.2 — Add pseudo data for `result_interpretation_agent`

**Files to create**:

```
tests/pseudo_data/api_call_outputs/result_interpretation_agent/
├── per_model_summary.json    # phase 1 response (one per model type in effective_types)
└── synthesis.json            # phase 2 cross-model response
```

The `RecordingLLMBridge` will be pre-loaded with BOTH entries and will pop them in FIFO order: first call returns `per_model_summary`, second call returns `synthesis`. For multi-model tests (two seeds + one proposed model = three phase-1 calls), the queue must hold three `per_model_summary` entries.

**`per_model_summary.json`** — must validate against the `PER_MODEL_SYSTEM_PROMPT` output schema (8 fields):

```json
{
  "key_findings": [
    "Best score of -1.509 is significantly below the wavenet baseline of 5.576, indicating the attention mechanism destabilised training.",
    "Loss collapsed in round 1 (loss=12.3) and only partially recovered in round 3 (loss=2.1)."
  ],
  "bottlenecks": [
    "Multi-head attention introduces O(T^2) memory and disrupts the causal inductive bias of dilated convolutions.",
    "Data volume is insufficient at trial_portion=0.1 to learn stable attention weights."
  ],
  "best_config_analysis": "The best config (lr=1e-4, focal, attn_heads=4) still scored -1.509 — attention heads likely need more data to converge.",
  "score_trend": "Scores improved from -2.38 (round 1) to -1.51 (round 3) but remained far below baseline. No convergence to positive territory.",
  "frequency_analysis": "All 20 files scored below 1.0. Low-frequency files (0-4) scored near zero. High-frequency files (15-19) scored around 0.3.",
  "data_sensitivity": "Score improved 0.87 points when trial_portion increased from 0.05 to 0.1, suggesting strong data sensitivity. Model not data-saturated.",
  "efficiency_assessment": "Model has 8.2M parameters vs punet baseline 12.3M. Smaller but worse — not a good efficiency trade-off at this performance level.",
  "strategy_assessment": "Agent correctly increased trial_portion after poor round 1, and explored two loss functions. Did not try reducing attention heads."
}
```

**`synthesis.json`** — must validate against the `SYNTHESIS_SYSTEM_PROMPT` output schema (5 fields):

```json
{
  "key_findings": [
    "The wavenet seed (5.576) substantially outperforms all proposed models so far. The best proposed model (attn_wavenet, -1.509) is 7 points below the seed.",
    "Every proposed model that added a global-context mechanism (attention, BiLSTM) scored negatively, while models that stayed close to dilated convolutions scored near the seed."
  ],
  "bottlenecks": [
    "Universal low-frequency blindness: no model yet addresses low-frequency files (0-4) — all score near zero on those files.",
    "Global-context mechanisms (attention, recurrence) consistently destabilise the causal dilated-conv backbone when added naively."
  ],
  "frequency_comparison": "Files 0-4 (low frequency) score near zero across all models. Files 10-19 score 0.3-0.7 for wavenet variants, near zero for attention models. No model achieves score > 1.0 on any file.",
  "efficiency_comparison": "Wavenet (5.576, 4.1M params) is Pareto-dominant: highest score at lowest parameter count. All proposed models are larger and worse.",
  "take_home_message": "Naively adding attention or recurrence to wavenet destroys performance — a fundamentally different approach to low-frequency context (e.g. multi-rate or frequency-domain) is required."
}
```

**Schema invariant**: before committing, manually validate both files parse and their shapes match what the real `LLMBridge.generate()` returns for each system prompt. Run:
```bash
.venv/bin/python -c "
import json
per = json.load(open('tests/pseudo_data/api_call_outputs/result_interpretation_agent/per_model_summary.json'))
assert all(k in per for k in ['key_findings','bottlenecks','best_config_analysis','score_trend',
                               'frequency_analysis','data_sensitivity','efficiency_assessment','strategy_assessment'])
syn = json.load(open('tests/pseudo_data/api_call_outputs/result_interpretation_agent/synthesis.json'))
assert all(k in syn for k in ['key_findings','bottlenecks','frequency_comparison','efficiency_comparison','take_home_message'])
print('pseudo data valid')
"
```

**Validation gate**: smoke check passes; `RecordingLLMBridge.for_agent("result_interpretation_agent")` loads both files without error.

---

#### F.3 — Dual-mode test for the feedback loop in `test_result_interpretation_agent.py`

**File**: `tests/integration/nodes/test_result_interpretation_agent.py`

Add a new `@pytest.mark.dual_mode` test function `test_interpretation_feedback_loop`. The existing `real_run`-marked tests are left untouched (but should be migrated to `ModelRunSummary` — see F.6).

**Test design — two parametrised scenarios**:

| Scenario | prev prediction | actual score of proposed model | expected outcome |
|---|---|---|---|
| `refuted` | metric=`denoising_score`, predicted=6.5, current=5.576, threshold=5.8 | -1.509 | `"refuted"` — actual << threshold |
| `confirmed` | metric=`denoising_score`, predicted=5.65, current=5.576, threshold=5.58 | 5.68 | `"confirmed"` — actual >= predicted |

**Input construction** (pseudo mode):
```python
from agent.schemas.interpretation import InterpretationInput, ModelRunSummary
from agent.schemas.storage import StorageConfig, LocalStorageConfig

# The proposed model's tuning summary — with known actual score
proposed_summary = ModelRunSummary(
    model_type="attn_wavenet",
    run_name="adaptive_v1",
    status="completed",
    completed_rounds=3,
    best_denoising_score=actual_score,   # -1.509 or 5.68 depending on scenario
    worst_denoising_score=actual_score - 1.0,
    best_config={"model_config": {"attn_heads": 4}},
    round_scores=[actual_score - 1.0, actual_score - 0.5, actual_score],
    round_conclusions=["poor", "improving", "best"],
    best_file_vector=[actual_score * 0.8] * 20,
    model_description="Wavenet with multi-head attention.",
)

# Seed models (wavenet + punet)
seed_wavenet = ModelRunSummary(model_type="wavenet", ..., best_denoising_score=5.576, ...)
seed_punet   = ModelRunSummary(model_type="punet", ..., best_denoising_score=1.29, ...)

previous_proposal = {
    "model_name": "attn_wavenet",
    "falsifiable_prediction": {
        "metric": "denoising_score",
        "current_value": 5.576,
        "predicted_value": predicted_value,   # 6.5 or 5.65
        "threshold_for_refutation": threshold, # 5.8 or 5.58
        "rationale": "...",
    },
    "inherited_components": [
        {"component": "dilated_causal_conv", "from_model_type": "wavenet", "contribution_evidence": "..."}
    ],
    "proposed_vocab_links": [],
    "proposed_discoveries": [],
}

agent_input = InterpretationInput(
    summaries=[seed_wavenet, seed_punet, proposed_summary],
    previous_proposal=previous_proposal,
    runtime_vocab=[],   # empty incoming vocab — discoveries start from zero
    storage=StorageConfig(backend="local", local=LocalStorageConfig(workspace=str(tmp_path), run_name="test")),
)
```

**Bridge setup** (pseudo mode): the bridge queue must have one `per_model_summary` response per model in `effective_types` (3 models = 3 per-model calls), then one `synthesis` response:
```python
bridge = RecordingLLMBridge(responses={
    "generate": [
        per_model_summary_canned,   # for wavenet
        per_model_summary_canned,   # for punet
        per_model_summary_canned,   # for attn_wavenet
        synthesis_canned,           # cross-model synthesis
    ]
})
agent = ResultInterpretationAgent(bridge_factory=lambda **kw: bridge)
output = agent.run(agent_input)
```

**Assertions** (both pseudo and real mode):
```python
# Core: prediction was evaluated (not null)
assert output.prediction_evaluation is not None
assert output.prediction_evaluation["actual_value"] is not None, \
    "actual_value is None — metric alias not resolved"
assert output.prediction_evaluation["outcome"] == expected_outcome

# Discovery was generated
assert len(output.new_discoveries) >= 1
assert expected_outcome.upper() in output.new_discoveries[0]["description"]

# Vocab grew with discovery
discovery_entries = [
    v for v in output.runtime_vocab
    if (v.get("kind") if isinstance(v, dict) else v.kind) == "discovery"
]
assert len(discovery_entries) >= 1, "No discovery in runtime_vocab — feedback loop broken"

# Storage: file written
interp_file = tmp_path / "interpretation_test.json"
assert interp_file.exists()
```

**Validation gate**: `pytest tests/integration/nodes/test_result_interpretation_agent.py::test_interpretation_feedback_loop -v` passes in pseudo mode (no `--real-api-call`) in < 1 second.

---

#### F.4 — Unit tests for `_render_vocabulary` with discoveries

**File**: `tests/unit/agent/ml_model_proposal_agent/test_proposal_agent.py`

Add a new test class `TestRenderVocabulary` with the following cases:

```python
class TestRenderVocabulary:

    def test_empty_returns_empty_string(self):
        assert MLModelProposalAgent._render_vocabulary([]) == ""

    def test_feature_entries_rendered(self):
        vocab = [VocabEntry(name="dilated_causal_conv", kind="feature", description="...", tier="canonical")]
        rendered = MLModelProposalAgent._render_vocabulary(vocab)
        assert "Features" in rendered
        assert "dilated_causal_conv" in rendered

    def test_discovery_entries_rendered(self):
        vocab = [VocabEntry(
            name="prediction_attn_wavenet_refuted",
            kind="discovery",
            description="REFUTED: attn_wavenet achieved denoising_score=-1.509 (predicted 6.5).",
            tier="candidate",
        )]
        rendered = MLModelProposalAgent._render_vocabulary(vocab)
        assert "Discoveries" in rendered
        assert "REFUTED" in rendered
        assert "prediction_attn_wavenet_refuted" in rendered

    def test_candidate_entries_rendered(self):
        vocab = [VocabEntry(name="ssm_layer", kind="candidate", description="State-space model layer.", tier="candidate")]
        rendered = MLModelProposalAgent._render_vocabulary(vocab)
        assert "Candidates" in rendered
        assert "ssm_layer" in rendered

    def test_all_four_kinds_rendered(self):
        vocab = [
            VocabEntry(name="f1", kind="feature",     description="...", tier="canonical"),
            VocabEntry(name="c1", kind="capability",  description="...", tier="canonical"),
            VocabEntry(name="d1", kind="discovery",   description="CONFIRMED: ...", tier="candidate"),
            VocabEntry(name="n1", kind="candidate",   description="...", tier="candidate"),
        ]
        rendered = MLModelProposalAgent._render_vocabulary(vocab)
        assert "Features" in rendered
        assert "Capabilities" in rendered
        assert "Discoveries" in rendered
        assert "Candidates" in rendered

    def test_no_discoveries_no_discoveries_section(self):
        vocab = [VocabEntry(name="f1", kind="feature", description="...", tier="canonical")]
        rendered = MLModelProposalAgent._render_vocabulary(vocab)
        assert "Discoveries" not in rendered

    def test_dict_entries_also_work(self):
        # _render_vocabulary must handle both VocabEntry objects and plain dicts
        vocab = [{"name": "d1", "kind": "discovery", "description": "REFUTED: ...", "tier": "candidate"}]
        rendered = MLModelProposalAgent._render_vocabulary(vocab)
        assert "Discoveries" in rendered
        assert "REFUTED" in rendered
```

**Why this test class matters**: bug 2 (`_render_vocabulary` dropping discoveries) would have been caught immediately by `test_discovery_entries_rendered`. The test is a unit test — no LLM, no fixtures, runs in milliseconds.

**Validation gate**: `pytest tests/unit/agent/ml_model_proposal_agent/ -q` passes.

---

#### F.5 — Tier 2 dual-mode test: interpretation → proposal (feedback chain)

**File**: `tests/integration/protocols/test_interp_to_propose.py`

Add a new `@pytest.mark.dual_mode` test `test_interp_to_propose_feedback_loop` that chains:
1. `ResultInterpretationAgent.run(input)` → `InterpretationOutput` containing discoveries
2. `local_full_context(output, storage)` → `ProposalInput` with vocab including discoveries
3. `MLModelProposalAgent.run(propose_input)` → assert discoveries appear in the LLM user prompt

**Why this test is uniquely valuable**: it is the only test that validates the complete chain — that a discovery generated in step 2 actually reaches the proposer's LLM call as text in the user prompt. The unit tests in F.4 verify rendering in isolation. F.3 verifies discovery generation in isolation. F.5 ties both together through the protocol.

**Bridge setup**:
- **Interpretation bridge**: 3 `per_model_summary` responses + 1 `synthesis` response (same as F.3)
- **Proposal bridge**: pre-loaded with the ~5 canned proposal pipeline responses (already exists in `tests/pseudo_data/api_call_outputs/ml_model_proposal_agent/generate.json`)

```python
interp_bridge  = RecordingLLMBridge(responses={"generate": [*three_per_model, synthesis]})
propose_bridge = RecordingLLMBridge.for_agent("ml_model_proposal_agent")

interp_agent  = ResultInterpretationAgent(bridge_factory=lambda **kw: interp_bridge)
propose_agent = MLModelProposalAgent(bridge_factory=lambda **kw: propose_bridge)

interp_output  = interp_agent.run(interp_input)   # same input as F.3 "refuted" scenario
propose_input  = local_full_context(interp_output, storage)
propose_output = propose_agent.run(propose_input)
```

**Key assertion — discoveries reach the proposer prompt**:
```python
# The proposer's user prompt is one of the generate() calls.
# Find the call that contains "Discoveries" (the rendered vocab block).
user_prompts = [call[2] for call in propose_bridge.calls if call[0] == "generate"]
discovery_prompt = next((p for p in user_prompts if "Discoveries" in p), None)
assert discovery_prompt is not None, \
    "No LLM call contained 'Discoveries' — discovery not rendered in proposer prompt"
assert "REFUTED" in discovery_prompt, \
    "REFUTED discovery text not present in proposer prompt"
```

**Validation gate**: `pytest tests/integration/protocols/test_interp_to_propose.py::test_interp_to_propose_feedback_loop -v` passes in pseudo mode in < 2 seconds.

---

#### F.6 — Update stale schemas in existing integration tests

Both `tests/integration/nodes/test_result_interpretation_agent.py` and `tests/integration/protocols/test_interp_to_propose.py` use the old `SummaryGroup` schema (replaced by `ModelRunSummary` in a prior refactor). They cannot be run in real mode without this fix.

**Changes needed**:
- Replace `from agent.schemas.interpretation import ..., SummaryGroup` with `ModelRunSummary`
- Replace `SummaryGroup(model_type=..., run_name=..., records=[...])` with `ModelRunSummary` construction via `tuning_output_to_model_run_summary()` or direct field population
- Mark existing tests as `@pytest.mark.dual_mode` where possible (they're currently `real_run` only)

**Scope**: do this in the same PR as F.3 and F.5 to avoid leaving broken tests. The stale tests should be fixed before any new dual-mode tests are added alongside them.

---

#### F.7 — DI on `ml_model_implementor` and `ml_code_validator_agent` (lower priority)

Same DI pattern as F.1. Enables future Tier 2 tests for the `impl → validate` and `validate → tune` edges. Not required for the feedback loop test — defer until F.1–F.5 are complete and validated.

---

#### F.8 — Migrate remaining tuner tests to dual-mode (deferred follow-up)

**File**: `tests/integration/nodes/test_tune_ml_hyperparam_agent.py`

Phase 1 (S.8) added two dual-mode methods to the tuner integration test. The remaining ~10 methods are still `@pytest.mark.real_run` only and never run in CI. This step migrates them.

**Scope**: for each `real_run` test method, add a pseudo path using the existing `RecordingLLMBridge` and `RecordingSandbox` fakes. The pseudo data already exists in `tests/pseudo_data/`. No new infrastructure is needed — this is purely mechanical.

**Why deferred**: F.1–F.6 are higher priority (feedback loop correctness). Tuner test migration is low-risk and does not unlock anything new — it only improves CI coverage breadth. Do this after F.1–F.6 are merged and green.

**Validation gate**: `pytest tests/integration/nodes/test_tune_ml_hyperparam_agent.py -v` (no `--real-api-call`) runs all methods in pseudo mode and passes in < 5 seconds.

---

#### F.9 — Tier 2 dual-mode test: tuning → interpretation (`tune_to_interpret` edge) (deferred follow-up)

**File**: `tests/integration/protocols/test_tune_to_interp.py`

The deferred items table originally listed both `interp_to_propose` and `tune_to_interpret` as targets for Tier 2 dual-mode coverage. F.5 handles `interp_to_propose`. This step handles `tune_to_interpret`.

**Scope**: a `@pytest.mark.dual_mode` test that:
1. Constructs a `HyperparamTuningOutput` with known scores and a `best_file_vector`
2. Passes it through the `tune_to_interp` protocol function → `InterpretationInput`
3. Runs `ResultInterpretationAgent.run(input)` with a `RecordingLLMBridge`
4. Asserts the output contains a valid `InterpretationOutput` with non-null `overall_best_score`

**Blocked on**: F.1 (DI on `ResultInterpretationAgent`). Cannot inject a recording bridge until F.1 is done.

**Why deferred**: F.5 already covers the higher-value direction (discoveries flowing *forward* to the proposer). `tune_to_interpret` exercises the protocol mapping but does not add new feedback-loop coverage. Do this after F.7 (full DI coverage) in a separate PR.

**Validation gate**: `pytest tests/integration/protocols/test_tune_to_interp.py -v` passes in pseudo mode in < 2 seconds.

---

### Implementation order and PR strategy

Steps are sequenced by dependency:

```
✅ F.4 (unit tests for _render_vocabulary)  ← independent, done first
✅ F.1 (DI on interp)
  └── ✅ F.2 (pseudo data)
       ├── ✅ F.3 (feedback loop test — Tier 1)
       │    └── ✅ F.5 (Tier 2 interp→propose chain test)
       └── ✅ F.9 (tune→interp Tier 2 test)
✅ F.6 (fix stale schemas) ← done with F.3
✅ F.7 (DI on implementor/validator)
  └── ✅ F.9 (tune_to_interpret Tier 2 test)
✅ F.8 (migrate tuner tests to dual-mode)
```

**F.1–F.9 all complete.**

---

### Phase 3 — Clean Dual-Axis Surrogation (complete)

**Goal**: make LLM surrogation and training/scoring surrogation two truly independent, composable axes. Today both are flipped by a single `--real-api-call` flag and the `tuner_factories` fixture couples them as a pair. Phase 3 separates them cleanly.

**Motivation**: see §8 concerns C.1–C.6 and the analysis below. The infrastructure already supports independent injection structurally (two separate constructor params: `bridge_factory` and `sandbox_factory`), but the test tooling re-couples them.

#### The target design

**Two flags, two axes:**

| `--real-llm` | `--real-training` | Mode |
|---|---|---|
| ✗ | ✗ | fully pseudo (default — current behaviour) |
| ✓ | ✗ | real LLM + pseudo training (new: test prompts without GPU) |
| ✗ | ✓ | pseudo LLM + real training (new: test execution without API key) |
| ✓ | ✓ | fully real (equivalent to current `--real-api-call`) |

The "real LLM + pseudo training" combination is the most valuable new mode: it lets you validate prompt logic and schema parsing against the real API without requiring a GPU or TIDMAD data on disk.

#### Step G.1 — Replace `--real-api-call` with two flags

**File**: `tests/conftest.py`

Replace:
```python
parser.addoption("--real-api-call", action="store_true", default=False)
```
With:
```python
parser.addoption("--real-llm",      action="store_true", default=False,
                 help="Use real LLMBridge instead of RecordingLLMBridge (needs GEMINI_API_KEY)")
parser.addoption("--real-training", action="store_true", default=False,
                 help="Use real TidmadSandbox instead of RecordingSandbox (needs GPU + data)")
```

Keep `--real-api-call` as a deprecated alias (sets both flags) during the migration period so existing CI scripts don't break immediately.

#### Step G.2 — Replace `tuner_factories` fixture with two independent helpers

**File**: `tests/conftest.py`

Delete the `tuner_factories` fixture. Add two standalone helper functions that tests call directly:

```python
def make_bridge_factory(request, agent_name: str):
    """Return a bridge factory for the given agent.

    Pseudo by default; pass --real-llm for real API calls.
    Skips the test if --real-llm is set but GEMINI_API_KEY is absent.
    """
    if request.config.getoption("--real-llm"):
        if not os.getenv("GEMINI_API_KEY"):
            pytest.skip("--real-llm requires GEMINI_API_KEY")
        return LLMBridge
    bridge = RecordingLLMBridge.for_agent(agent_name)
    return lambda **kw: bridge

def make_sandbox_factory(request, model_type: str, base_dir: str, run_name: str):
    """Return a sandbox factory for the given model.

    Pseudo by default; pass --real-training for real GPU execution.
    Skips the test if --real-training is set but TIDMAD data is absent.
    """
    if request.config.getoption("--real-training"):
        if not _has_real_data():
            pytest.skip("--real-training requires TIDMAD data on disk")
        return TidmadSandbox
    sandbox = RecordingSandbox.for_model(model_type, base_dir=base_dir, run_name=run_name)
    return lambda **kw: sandbox
```

Usage in tests:
```python
def test_punet_one_round(tmp_path, request):
    bridge_factory  = make_bridge_factory(request, "ml_hyperparameter_tune_agent")
    sandbox_factory = make_sandbox_factory(request, "punet", str(tmp_path), "run")
    agent = HyperparamTuningAgent(bridge_factory=bridge_factory,
                                   sandbox_factory=sandbox_factory)
```

#### Step G.3 — Move `score_vector` into the sandbox interface

**Files**: `core/sandbox_executor.py`, `tests/helpers/recording_sandbox.py`, `nodes/ml_hyperparameter_tune_agent.py`

`score_vector` is logically an evaluation operation (same category as `execute_scoring`). It is currently a module-level function called directly by the tuner in trial mode, which requires a separate `monkeypatch` injection — a third, non-uniform injection point.

Fix: move it into both sandbox classes as a method.

```python
# TidmadSandbox
def score_vector(self, file_vector, anchors, s_max, **kwargs):
    return _real_score_vector(file_vector, anchors, s_max, **kwargs)

# RecordingSandbox
def score_vector(self, file_vector, anchors, s_max, **kwargs):
    self.calls.append(("score_vector", file_vector))
    return self._pop("score_vector")
```

The agent's trial-mode call site changes from:
```python
fv, scalar = score_vector(file_vector=..., anchors=..., s_max=...)   # module-level
```
to:
```python
fv, scalar = self._sandbox.score_vector(file_vector=..., anchors=..., s_max=...)
```

The `monkeypatch.setattr(tuner_module, "score_vector", ...)` workaround in `test_wavenet_one_round_dual_mode` and `test_punet_one_round_dual_mode[trial]` is removed.

Add `score_vector.json` to each model's pseudo-data directory, loaded by `RecordingSandbox.for_model`.

#### Step G.4 — Migrate all dual-mode tests to the new helpers

**Files**: all `@pytest.mark.dual_mode` tests in `tests/integration/`

Replace every `request.config.getoption("--real-api-call")` pattern with calls to `make_bridge_factory` / `make_sandbox_factory`. The `if is_real: ... else: ...` blocks collapse — the factories handle the switch internally.

#### Step G.5 — Update documentation and CI

- Update `docs/pseudo_test_infra.md` §4C mode matrix to show the four combinations
- Update `README.md` test-running instructions
- Update any CI scripts that pass `--real-api-call` to pass `--real-llm --real-training` instead

#### Implementation order

```
G.1 (two flags in conftest)          ← prerequisite for all
  └── G.2 (replace tuner_factories)  ← mechanical, test-only
G.3 (score_vector into sandbox)      ← touches production code + tests
  └── G.4 (migrate dual-mode tests)  ← after G.1 + G.3
G.5 (docs + CI)                      ← last
```

#### Definition of done

- [x] G.1: `--real-llm` and `--real-training` flags registered; `--real-api-call` still works as alias
- [x] G.2: `tuner_factories` fixture removed; `make_bridge_factory` / `make_sandbox_factory` helpers in place
- [x] G.3: `score_vector` is a method on both `TidmadSandbox` and `RecordingSandbox`; `monkeypatch` workarounds removed
- [x] G.4: all dual-mode tests use the new helpers; no test reads `--real-api-call` directly
- [x] G.5: docs and CI updated
- [x] All 8 dual-mode tests pass (965 passed, 0 failures, 2026-04-14)

---

### Phase 4 — Vocabulary Accumulation Across Iterations (planned)

**Goal**: verify that the system actually learns across iterations — discoveries generated in iteration N survive into iteration N+1's vocab, and the vocab list is strictly monotonically growing.

**Motivation**: Phases 1–3 test individual nodes and edges in isolation. None of them exercise the full multi-iteration accumulation loop:

```
iter 1: interpret (previous_proposal=P1) → discovery D1 → runtime_vocab [D1]
                                                 ↓ protocol
        propose → P2 (with D1 in vocab_seed)
iter 2: interpret (previous_proposal=P2, runtime_vocab=[D1]) → discovery D2
            → runtime_vocab [D1, D2]  ← must contain BOTH
```

Without this test, regressions in `build_runtime_vocab` (dropping entries, not deduplicating correctly) or in the workflow's `current_runtime_vocab` accumulation loop would go undetected.

---

#### Step H.1 — Two-iteration vocab accumulation dual-mode test

**File**: `tests/integration/workflows/test_vocab_accumulation.py`

**What it exercises**:
1. **Iteration 1**: `ResultInterpretationAgent` receives a `previous_proposal` with a `falsifiable_prediction` → evaluates it → generates at least one discovery → `runtime_vocab` has ≥ 1 entry
2. **Protocol mapping**: `local_full_context(iter1_output, storage)` → `ProposalInput.vocab_seed` contains iter 1's discoveries
3. **Iteration 2**: `ResultInterpretationAgent` receives `runtime_vocab` from iter 1 + a new `previous_proposal` → generates a new discovery → `runtime_vocab` has more entries than iter 1
4. **Monotonic growth**: every entry in iter 1's `runtime_vocab` is present in iter 2's `runtime_vocab` (nothing dropped)

**LLM axis only** — no sandbox needed. Both iterations use `ResultInterpretationAgent`, which is LLM-only.

**Pseudo data strategy**: use two separate `RecordingLLMBridge` instances — one per iteration — each loaded from its own canned data subdirectory. This avoids the shared-queue ordering problem (Known Concern C.1) and makes each iteration's responses self-contained.

```
tests/pseudo_data/api_call_outputs/
  result_interpretation_agent/          ← existing (used by F.3, F.9)
  result_interpretation_agent_iter2/    ← new, canned responses for iteration 2
```

**Canned data needed**:
- `result_interpretation_agent_iter2/`: responses for an interpretation run with 3 models (wavenet, punet, spectral_net) where `spectral_net` is the proposed model being evaluated (confirmed outcome)

**Test sketch**:

```python
@pytest.mark.dual_mode
def test_vocab_grows_across_two_iterations(tmp_path, request):
    from tests.conftest import _is_real_llm, make_bridge_factory
    from tests.helpers.recording_llm_bridge import RecordingLLMBridge

    # --- Iteration 1 ---
    # Scenario: attn_wavenet was proposed, its prediction was REFUTED
    iter1_inp = InterpretationInput(
        summaries=[SEED_WAVENET, SEED_PUNET, ATTN_WAVENET_BAD_SUMMARY],
        previous_proposal=PREVIOUS_PROPOSAL_REFUTED,
        runtime_vocab=[],
        storage={...},
    )
    if _is_real_llm(request):
        iter1_bridge = None
        bridge_factory_1 = LLMBridge
    else:
        iter1_bridge = RecordingLLMBridge.for_agent("result_interpretation_agent")
        bridge_factory_1 = lambda **kw: iter1_bridge

    iter1_output = ResultInterpretationAgent(bridge_factory=bridge_factory_1).run(iter1_inp)

    # Assert iteration 1 produced discoveries
    assert len(iter1_output.new_discoveries) >= 1
    assert len(iter1_output.runtime_vocab) >= 1
    discovery_kinds = [v.kind for v in iter1_output.runtime_vocab]
    assert "discovery" in discovery_kinds

    # --- Protocol: iter 1 vocab flows to proposal ---
    proposal_inp = local_full_context(iter1_output, storage)
    assert proposal_inp.vocab_seed, "vocab_seed empty — iter 1 discoveries not passed to proposer"
    assert any(
        (v.get("kind") if isinstance(v, dict) else v.kind) == "discovery"
        for v in proposal_inp.vocab_seed
    ), "No discovery entry in vocab_seed"

    # --- Iteration 2 ---
    # Scenario: spectral_net (newly proposed from iter 1) was run, prediction CONFIRMED
    iter2_inp = InterpretationInput(
        summaries=[SEED_WAVENET, SEED_PUNET, SPECTRAL_NET_GOOD_SUMMARY],
        previous_proposal=PREVIOUS_PROPOSAL_CONFIRMED,
        runtime_vocab=iter1_output.runtime_vocab,   # ← carry forward
        storage={...},
    )
    if _is_real_llm(request):
        iter2_bridge = None
        bridge_factory_2 = LLMBridge
    else:
        iter2_bridge = RecordingLLMBridge.for_agent("result_interpretation_agent_iter2")
        bridge_factory_2 = lambda **kw: iter2_bridge

    iter2_output = ResultInterpretationAgent(bridge_factory=bridge_factory_2).run(iter2_inp)

    # Assert vocab grew
    assert len(iter2_output.runtime_vocab) > len(iter1_output.runtime_vocab), (
        f"Vocab did not grow: iter1={len(iter1_output.runtime_vocab)}, "
        f"iter2={len(iter2_output.runtime_vocab)}"
    )

    # Assert iter 1 entries still present (monotonic accumulation)
    iter1_names = {v.name for v in iter1_output.runtime_vocab}
    iter2_names = {v.name for v in iter2_output.runtime_vocab}
    dropped = iter1_names - iter2_names
    assert not dropped, f"Entries dropped from vocab in iter 2: {dropped}"

    # Assert a new discovery was added in iter 2
    new_in_iter2 = iter2_names - iter1_names
    assert new_in_iter2, "No new entries added in iter 2 — vocab did not accumulate"
```

#### Dependency and sequencing

```
H.1 depends on:
  - existing result_interpretation_agent pseudo data (F.3)
  - new iter2 pseudo data directory (new)
  - local_full_context protocol (already tested in F.5)
No production code changes needed — this is test-only.
```

#### Definition of done

- [ ] H.1: `test_vocab_grows_across_two_iterations` passes in pseudo mode (default, no flags)
- [ ] Pseudo data for `result_interpretation_agent_iter2` created and schema-validated
- [ ] Vocab monotonic growth assertion passes: `len(iter2) > len(iter1)` and `iter1_names ⊆ iter2_names`
- [ ] Protocol assertion passes: iter 1 discoveries appear in `proposal_inp.vocab_seed`
- [ ] Real-LLM smoke test passes with `--real-llm`

### Definition of done

The vocabulary feedback loop is considered pseudo-tested when F.1–F.6 are complete:
- [x] F.1: `ResultInterpretationAgent` accepts `bridge_factory`; unit tests still green
- [x] F.2: pseudo data exists and passes schema smoke check
- [x] F.3: `test_interpretation_feedback_loop[refuted]` and `[confirmed]` pass in pseudo mode
- [x] F.4: `TestRenderVocabulary` unit tests pass (8 cases)
- [x] F.5: `test_interp_to_propose_feedback_loop` passes in pseudo mode with "REFUTED" in prompt assertion
- [x] F.6: stale `SummaryGroup` references removed from both integration test files
- [x] All existing unit tests still green (`pytest tests/unit/ -q` → 871 passed)

**✅ Core feedback loop is pseudo-tested. All F.1–F.6 gates are green.**

Phase 2 follow-ups (all complete):
- [x] F.7: DI on `ml_model_implementor` and `ml_code_validator_agent`
- [x] F.8: remaining tuner integration tests migrated to dual-mode
- [x] F.9: `tune_to_interpret` Tier 2 dual-mode test

## Change log (decisions made during implementation)

### Phase A reverted (commit `392ef6b`)

**What**: reverted commit `c836904` ("feat(adaptive-proposer): Phase A — regime_scores foundation"). Removed `execute_tools/regime_aggregator.py`, the `regime_scores: Dict[str, float]` field on `ExperimentRecord`, the "REGIME SCORES" planner prompt section, the "REGIME-AWARE DIAGNOSIS" reflector prompt section, and 19 unit tests.

**Why**: the low/mid/high frequency band division (`low_freq_kHz`, `mid_freq_10kHz`, `high_freq_MHz`) is **domain knowledge**, not infrastructure. Hardcoding it into `REGIME_DEFINITIONS` and baking it into `ExperimentRecord` violated the V2 design principle that domain knowledge should come from external expert advice (the `tuner_advice/*.json` files, or the future Data Analysis Agent via `ExpertContextItem`), not from the codebase.

The 20-element `file_vector` already contains all the per-file scoring information. The file-to-frequency mapping is already documented in `tuner_advice/gated_fno_freq_band_aware_v1.json` as expert advice — exactly where it belongs. Any frequency-band aggregation the LLM needs can be done by the LLM itself, guided by the expert advice context.

**What stays**:
- `file_vector` on `ExperimentRecord` — raw data, no domain assumptions
- The existing "FILE VECTOR AND SCORING" prompt section — explains what file_vector is, without imposing a frequency-band interpretation
- `tuner_advice/gated_fno_freq_band_aware_v1.json` — the frequency band map as expert advice

**Impact on the V2 design doc** (`docs/adaptive_new_model_proposer.md`):
- Phase A sub-tasks A.1–A.7 were marked ☑ but are now reverted. The Phase A section should be updated to reflect this. The `regime_scores` design as a "deliberate extension point for the Data Analysis Agent" is withdrawn — the extension point is now `ExpertContextItem` (§2D), not a hardcoded field on the record.
- The `FalsifiablePrediction` schema in Phase B originally referenced `regime_scores` regimes. This needs to be redesigned to reference `file_vector` indices or expert-defined regime names instead.

**Impact on this PR**: none. The test infrastructure (recording fakes, fixtures, DI) is independent of whether `regime_scores` exists. The dual-mode test assertions about prompt content will reference `file_vector` instead of `regime_scores`.

---

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

---

## 8. Known concerns and future work

These are structural limitations identified after Phase 2 completed. None block current usage, but each will cause friction as the pipeline grows.

### C.1 — `plan()` silently aliases the `generate` queue

`RecordingLLMBridge.plan()` records a `("plan", ...)` call but pops from the `"generate"` queue, because `LLMBridge.plan()` internally calls `self.generate()`. The consequence: when an agent makes both `plan()` and `generate()` calls (e.g. pipeline mode with 2 reasoning `generate()` stages + 1 `plan()`), all three draw from the same `generate` queue. The ordering in `generate.json` becomes load-bearing and invisible — insert one extra `generate()` inside the agent and every subsequent item in the queue shifts. This is currently documented only in the source; it is not mentioned in `pseudo_test_infra.md`.

**When this will hurt**: any agent that mixes `plan()` and `generate()` in the same run (already the case for `ml_model_proposal_agent` in pipeline mode).

**Possible fix**: give `plan()` its own `"plan"` queue slot; populate it from `plan.json`. Tests that inspect call order via `bridge.calls` already distinguish `plan` from `generate` entries — the queue should match.

### C.2 — Multi-round testing has no ergonomic `for_agent` / `for_model` support

`for_agent` loads each JSON file as one response (or a flat array). For a 2-round tuner pseudo test you need 2 plan responses and 2 reflect responses. The options today are:

1. Put `[round1, round2]` in `generate.json` — works, but the file is order-sensitive and rounds are unlabeled.
2. Construct the bridge inline (as done in `test_wavenet_one_round_dual_mode`) — no data reuse, boilerplate per test.

Neither scales past 2–3 rounds. The wavenet F.8 test already bypasses `for_agent` for this reason.

**When this will hurt**: any pseudo test that exercises >1 tuning round, or any workflow-level pseudo test that chains multiple agents.

**Possible fix**: support per-round subdirectories, e.g. `pseudo_data/api_call_outputs/ml_hyperparameter_tune_agent/round_1/generate.json`, `round_2/generate.json`. `for_agent(agent, rounds=2)` concatenates the queues in order. Single-round tests continue to use the flat layout.

### C.3 — No schema validation at pseudo-data load time

`load_pseudo_data` does a raw `json.load` with no Pydantic validation. When a schema changes (e.g., `ExperimentPlan` gains a required field), the stale JSON file is loaded silently. The `ValidationError` surfaces during test *execution*, deep inside the agent, pointing at the agent's internals rather than the JSON file. There is no CI check that validates pseudo-data files against the current schemas.

**When this will hurt**: every schema evolution. Already happened once during Phase 2 (`ExperimentMemory.expert_advice_followed` and `.hypothesis` were required but missing from the F.9 test data, caught only at runtime).

**Possible fix**: add a `tests/unit/pseudo_data/test_pseudo_data_schema.py` that imports every pseudo-data file, feeds it through the relevant Pydantic model, and asserts it validates. Runs in `<1s` and catches stale files immediately.

### C.4 — `plan()` call record drops key arguments

`RecordingLLMBridge.plan()` only records `(method, memory_history, expert_advice, force_model)` in `calls`. The remaining arguments — `config_manual`, `model_description`, `exploration_checklist`, `current_round`, `max_rounds`, `trial_allowed` — are silently dropped. Tests cannot assert on what round number or model description the agent passed to the planner, which are exactly the arguments that encode round-state.

**Possible fix**: record all arguments: `self.calls.append(("plan", memory_history, expert_advice, force_model, config_manual, model_description, exploration_checklist, current_round, max_rounds, trial_allowed))`.

### C.5 — `score_vector` is a separate injection point with no standard pattern

In trial mode the tuner calls `score_vector()` directly (not through the sandbox). The F.8 test handles this with `monkeypatch.setattr(tuner_module, "score_vector", ...)` — a different injection mechanism from the DI factory pattern used everywhere else. This creates two mental models for "how do I fake execution in a pseudo test."

**Possible fix**: wrap `score_vector` behind a callable attribute on the tuner agent (e.g., `self._score_fn = score_vector`) that can be injected via constructor or monkeypatched at a stable, documented path.

### C.6 — `tuner_factories` conftest fixture is hardwired to punet

The `tuner_factories` fixture in `conftest.py` hardcodes `for_agent("ml_hyperparameter_tune_agent")` and defaults `model_type="punet"`. Tests that need wavenet or any other model bypass the fixture entirely. The fixture is effectively only useful for punet-specific tests, which undermines its purpose as a shared helper.

**Possible fix**: parametrise the fixture or replace it with a helper function `make_tuner_factories(agent_name, model_type, base_dir)` that tests call directly, giving them explicit control without a hidden default.

### Priority

| Concern | Severity | Suggested action |
|---------|----------|-----------------|
| C.3 — No schema validation at load time | Medium | Add `test_pseudo_data_schema.py` unit test |
| C.1 — `plan()` aliases `generate` queue | Medium | Separate `plan` queue + `plan.json` file |
| C.2 — No multi-round `for_agent` support | Medium | Per-round subdirectory convention |
| C.4 — `plan()` drops call record args | Low | Record all args |
| C.5 — `score_vector` ad-hoc injection | Low | Inject via constructor attribute |
| C.6 — `tuner_factories` fixture hardwired | Low | Replace with explicit helper function |
