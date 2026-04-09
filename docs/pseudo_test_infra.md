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

A test double for `LLMBridge` that:
- Implements the same public interface (`generate`, `reflect`, `generate_text`, `tool_call`).
- Records every call: method name, system prompt, user prompt, returned value, timestamp.
- Returns canned responses configured before the test runs. Supports per-call queueing (round 1 returns response A, round 2 returns response B).
- Exposes the recorded calls as a list so tests can assert on prompt content, call count, call order.

Sketch:
```python
class RecordingLLMBridge:
    def __init__(self, canned_responses: dict[str, list] | None = None):
        self.calls: list[RecordedCall] = []
        self._canned = canned_responses or {}

    def generate(self, system_prompt: str, user_prompt: str) -> dict:
        return self._record_and_return("generate", system_prompt, user_prompt)

    def reflect(self, exp_id, hypothesis, results, context) -> dict:
        return self._record_and_return("reflect", exp_id=exp_id, ...)

    # ... and so on for generate_text, tool_call
```

#### `RecordingSandbox`

A test double for `TidmadSandbox` that:
- Implements the same public interface (`execute_training`, `execute_inference`, `execute_scoring`, `save_record`, `dirs`, …).
- Returns canned `train_status` / `inference_status` / `score_res` payloads configured before the test runs.
- Records every call so tests can assert on what configs were passed to training, what file_index was used, etc.
- Stores `save_record` calls in an internal list so tests can inspect the records the orchestration tried to persist.

Sketch:
```python
class RecordingSandbox:
    def __init__(self, base_dir: str, canned: dict | None = None):
        self.base_dir = base_dir
        self.dirs = {"data": "/fake/data", "configs": "/fake/configs", ...}
        self.calls: list[RecordedCall] = []
        self.saved_records: list[dict] = []
        self._canned = canned or {}

    def execute_training(self, exp_id, run_name, model_type, m_cfg, t_cfg, l_cfg, ...):
        self.calls.append(...)
        return self._canned.get("execute_training", {"status": "success", "results": {...}})

    def save_record(self, record: dict):
        self.saved_records.append(record)
    # ... and so on
```

### 4C. Fixture-based mode switching (locked design: orthogonal axes)

A pytest fixture decides which factories to inject based on a CLI flag, and the existing `pytest.mark.real_run` marker is preserved for a separate, orthogonal purpose.

**Two independent axes**:

| Concept | Mechanism | What it means |
|---|---|---|
| **Test category** | `pytest.mark.real_run` | "This test only works in real mode — it has no pseudo equivalent (e.g. it asserts on actual LLM output structure that no canned response could meaningfully validate)." Reserved for the rare case where pseudo mode genuinely cannot validate the thing. |
| **Execution mode** | `--real-api-call` CLI flag | "When pytest runs today, use the real `LLMBridge` / `TidmadSandbox` instead of the recording fakes." Pseudo mode is the default; real mode requires explicit opt-in. |

These axes are independent. A test can be:

- **Dual-mode** (no marker): runs in pseudo mode by default; runs in real mode if `--real-api-call` is passed. **This is the recommended pattern for almost every test.**
- **Real-only** (marked `real_run`): skipped by default; runs only when both the marker is selected AND the flag is passed. Reserved for tests that have no canned-response equivalent.

**Combination matrix**:

| Command | Dual-mode tests | Real-only tests (marked `real_run`) |
|---|---|---|
| `pytest tests/integration/` | run in **pseudo** mode | skipped |
| `pytest tests/integration/ --real-api-call` | run in **real** mode | skipped (still need `-m`) |
| `pytest tests/integration/ -m real_run` | skipped (no marker) | skipped (need flag too) |
| `pytest tests/integration/ -m real_run --real-api-call` | skipped | run in real mode |

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

- ☐ **S.1** Write `tests/helpers/recording_llm_bridge.py` with the `RecordingLLMBridge` class. Public interface mirrors `LLMBridge.generate / reflect / generate_text / tool_call / list_models`. Internal: per-call canned response queue, recorded call list, helpful repr for test debugging.
- ☐ **S.2** Write `tests/helpers/recording_sandbox.py` with the `RecordingSandbox` class. Public interface mirrors `TidmadSandbox.execute_training / execute_inference / execute_scoring / save_record / dirs`. Internal: canned payloads keyed by method, recorded call list, `saved_records` list for persistence assertions.
- ☐ **S.3** Write `tests/helpers/test_recording_doubles.py` — unit tests for the test doubles themselves. The doubles are infrastructure code and need their own tests so future contributors trust them. Cover: canned response delivery, call recording, queue exhaustion behavior, default-canned-response fallback.
- ☐ **S.4** Add `pytest_addoption` and the `tuner_factories` fixture to `tests/conftest.py` (creating it if absent). The CLI flag `--real-api-call` is the primary mode selector. Pseudo is default.
- ☐ **S.5** Add constructor DI to `HyperparamTuningAgent`: optional `bridge_factory` and `sandbox_factory` parameters defaulting to `LLMBridge` and `TidmadSandbox`. Replace internal `LLMBridge(...)` and `TidmadSandbox(...)` calls with `self._bridge_factory(...)` and `self._sandbox_factory(...)`. **No behavioral change in production**: when factories aren't passed, the agent constructs the real classes exactly as before.
- ☐ **S.6** Refactor `tests/integration/nodes/test_tune_ml_hyperparam_agent.py::TestRealRunGemini::test_punet_gemini[loss_cfg0]` to dual-mode. Use the `tuner_factories` fixture. In pseudo mode, configure the recording fakes with a canned plan + canned reflection + canned train/score results, run the agent, assert on (a) the planner system prompt content, (b) the saved record's structure, (c) the reflector's input. In real mode, the same test runs end-to-end against the real API as it does today. **Zero change to behavior in real mode**; new behavior in pseudo mode.
- ☐ **S.7** Run the full unit suite plus the new pseudo-mode test in CI configuration (no `--real-api-call`). All existing tests continue to pass. The newly-refactored test passes in pseudo mode.
- ☐ **S.8** Update `docs/architecture.md`: new "Pseudo-full-loop tests" section after the existing Testing Strategy section, new principle 10 in Core Principles, updated taxonomy table.
- ☐ **S.9** Update `CLAUDE.md` if needed (one-line addition under Coding Standards) referencing the new tier.

### Cross-step verification gates

- After S.1, S.2, S.3: `uv run pytest tests/helpers/ -q` passes.
- After S.5: `uv run pytest tests/unit/ -q` still passes (no production behavior change).
- After S.6: `uv run pytest tests/integration/nodes/test_tune_ml_hyperparam_agent.py::TestRealRunGemini::test_punet_gemini -q` (pseudo mode, no `--real-api-call`) passes in milliseconds.
- After S.6: `uv run pytest tests/integration/nodes/test_tune_ml_hyperparam_agent.py::TestRealRunGemini::test_punet_gemini -q --real-api-call -m real_run` (real mode) still passes — verifying the refactor didn't break the existing real-mode behavior.
- After S.7: `uv run pytest tests/unit/ tests/helpers/ -q` is fully green.

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

## 7. Open questions

1. ☑ **Mode selector** (see §4C). **Resolved**: orthogonal axes — `--real-api-call` flag for execution mode + existing `pytest.mark.real_run` marker for test category. Two independent concepts; pseudo is the default.
2. **Recording fakes location**. `tests/helpers/` vs `tests/fakes/` vs `tests/doubles/`. Recommendation: `tests/helpers/` — most conventional in the Python ecosystem.
3. **Canned response API shape**. Should the recording fakes accept canned responses (a) at construction time as a dict, (b) at call time via a per-test `register_response()` method, or (c) both? Recommendation: both — dict at construction for simple cases, `register_response()` for round-by-round queues. Defer the decision until S.1/S.2 to see what's natural.
4. **Should `RecordingSandbox` actually create the workspace dirs on disk** (mirroring `TidmadSandbox.__init__`'s `_ensure_dir` calls), or stay fully in-memory? In-memory is faster but breaks any node code that does `os.path.exists(sandbox.dirs["configs"])`. Recommendation: use `tmp_path` from pytest so the dirs exist on disk in a temp location, get cleaned up automatically. Decide at S.2.
5. **How to handle the tuner's many-roles call sites**. The tuner builds `bridge` and `sandbox` once per `run()` call. Some sub-skills (training/inference/scoring wrappers) construct their own — those need to thread the factory through too. Decide concretely during S.5; the answer will inform whether other nodes need a similar audit before they can be retrofitted.
