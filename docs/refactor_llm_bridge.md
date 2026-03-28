# LLMBridge Refactor: Unified OpenAI Interface

## Status: Phase 1 COMPLETE — all sub-phases done, tests rewritten and passing

---

## Motivation

`agent/llm_bridge.py` previously maintained two parallel code paths (`google-genai` SDK
for Gemini, `openai` SDK for OpenAI). Every method (`generate`, `generate_text`, `request`)
had an `if provider == "gemini" / elif provider == "openai"` branch. This doubled the
surface area for bugs and made adding a third provider require editing every method.

Google provides an [OpenAI-compatible endpoint](https://ai.google.dev/gemini-api/docs/openai)
so Gemini can be called through the `openai` SDK. Phase 1 migrated to a single SDK and
eliminated the branching entirely.

---

## Phase 1: Architecture Unification (OpenAI SDK Only) — COMPLETE

**Goal**: Eliminate `google-genai` dependency; use `openai.OpenAI` for all providers.

### [x] 1.1 Unify Client Initialization

Refactored `__init__` to use a single `openai.OpenAI` client for all providers.

**What changed:**
- Removed `from google import genai` and `from google.genai import types` imports.
- Single `OpenAI(api_key=..., base_url=...)` client handles all providers.
- Known providers (`"openai"`, `"gemini"`) auto-resolve `base_url`, `api_key` (from env),
  and `default_model` via the `_KNOWN_PROVIDERS` map — convenience, not a restriction.
- Unknown providers are fully supported by passing `base_url` and `api_key` explicitly
  (e.g. `LLMBridge(provider="custom", base_url="...", api_key="...", model_id="...")`).
- Added `list_models()` method that queries the provider's `GET /models` endpoint.
- Default Gemini model updated from `gemini-3-flash` (stale) to `gemini-3.1-flash-lite-preview`.

**URL correction:** the original proposal had `generativeai.googleapis.com` which returns 404.
The correct endpoint (verified via Google docs and live test) is:
`https://generativelanguage.googleapis.com/v1beta/openai/`

**API key resolution order:** explicit `api_key` arg > env var from known-providers map > `None`.
`load_dotenv()` is still called, so `.env` files work as before.

**Live-tested:** both `LLMBridge(provider="gemini")` and `LLMBridge(provider="openai")`
successfully completed a `chat.completions.create` call through the unified client.

### [x] 1.2 Standardize `generate` and `generate_text`

- Removed all provider-specific `if/else` branching from both methods.
- Single `client.chat.completions.create` call handles all providers.
- `generate()`: uses `response_format={"type": "json_object"}`, keeps markdown fence
  stripping (provider-agnostic), error message now includes provider/model name.
- `generate_text()`: plain `chat.completions.create` with no response format constraint.
- Live-tested: both methods work for `gemini` and `openai` providers.

### [x] 1.3 Delete dead code: `request()` method

Deleted `request()` and removed the unused `Any` import. No callers existed anywhere in
the codebase. Integration tests still pass (4/4).

> **Changed from original proposal**: the original plan was to refactor `request()` to
> align Gemini's tool-calling with OpenAI's schema. Since no caller exists, deletion is
> simpler and avoids untested code.

### [x] 1.4 Update `pyproject.toml` and `uv.lock`

- Removed `google-generativeai>=0.8.6` from `[project.dependencies]`.
- `uv lock` removed 16 transitive packages (google-api-core, grpcio, protobuf, etc.).
- Also updated `env_validation/test_agent_env.py` which was the only other file importing
  the old `google.generativeai` SDK — now uses `LLMBridge` directly.
- Integration tests and env validation both pass.

### [x] 1.5 Rewrite unit tests

- Rewrote `tests/unit/agent/test_llm_bridge.py` — 18 tests, all passing.
- All mocks now target `openai.OpenAI` only (no `genai.Client`).
- New test classes: `TestInit` (7 tests for provider resolution, overrides, unknown
  providers), `TestListModels` (1 test), `TestGenerate` (6 tests including
  provider-agnostic check), `TestGenerateText` (4 tests).
- Deleted: `TestProviderValidation` (unknown providers are now allowed),
  all `request()` tests (method deleted).
- Integration tests (`tests/integration/nodes/test_llm_bridge.py`) pass unchanged (4/4).
- Full unit suite: 504 passed, 0 broken.

---

## Files changed in Phase 1

| File | Change |
|------|--------|
| `agent/llm_bridge.py` | Unified client, removed branching, deleted `request()`, added `list_models()`, added module-level architecture doc |
| `pyproject.toml` | Removed `google-generativeai` dependency |
| `uv.lock` | Regenerated (16 packages removed) |
| `env_validation/test_agent_env.py` | Migrated from `google.generativeai` to `LLMBridge` |
| `tests/unit/agent/test_llm_bridge.py` | Full rewrite (18 tests) |

### Files verified unchanged (no edits needed)

- 5 node classes: interface preserved, all use `generate()` / `generate_text()` / `plan()` / `reflect()` unchanged
- 5 node-level unit test files: mock `LLMBridge` at module path, unaffected
- `workflows/llm_config.py`: `Literal["gemini", "openai"]` still valid
- `workflows/model_exploration.py`: hardcoded defaults still work
- `tests/integration/nodes/test_llm_bridge.py`: passes without changes (4/4)

---

## Phase 2: Robustness & Data Integrity

**Goal**: Harden the bridge for long research sessions.

### [ ] 2.1 Enhance JSON Parsing Safety

- `generate()` already has `try/except` and markdown fence stripping after Phase 1.2.
- Remaining: consider raising instead of returning `{}` on parse failure, to make errors
  visible rather than silently propagating empty dicts through the graph.

### [ ] 2.2 Context History Management

- Verify `memory_history` mapping to `{"role": "user/assistant", "content": "..."}`.
- **Scope note**: `memory_history` is only used in `plan()`, which is only called by
  `ml_hyperparameter_tune_agent`. This is a tuning-agent concern, not a bridge-wide
  issue. Consider whether `plan()` and `reflect()` should remain on the bridge or move
  to the tuning agent's own code (they are domain-specific, not generic transport).

### [ ] 2.3 Implement Error Handling & Retries

- Add retry logic for `RateLimitError` (HTTP 429) with exponential backoff.
- Suggestion: use `tenacity` for the retry decorator.
- Both providers now raise `openai.RateLimitError` (unified SDK), simplifying this.

---

## Phase 3: Research-Specific Optimizations

**Goal**: Improve how physical constraints and expert advice are injected.

### [ ] 3.1 Optimize Physical Constraint Injection

Instead of appending `config_manual` to `user_prompt` as a string, inject it as a
separate system/developer message for higher attention priority.

> **Scope note**: Like `plan()`/`reflect()`, this only affects the tuning agent. If
> those methods move out of the bridge (see 2.2), this task moves with them.

### [ ] 3.2 Enable Asynchronous Support (`AsyncOpenAI`)

Transition the bridge to `AsyncOpenAI` to allow parallel LLM calls.

> **Recommendation**: This is a significant scope expansion. All 5 node classes and the
> workflow orchestrator would need `async`/`await` changes. Defer to a separate PR after
> Phase 1 is stable.

### [ ] 3.3 Prompt Compatibility Audit

Ensure `PLANNER_PROMPT` and `REFLECTOR_PROMPT` in `agent/prompts.py` explicitly contain
"Return a valid JSON object" — required by OpenAI's `json_object` response format.

---

## Open Questions

1. **Should `plan()` and `reflect()` stay on `LLMBridge`?** They are domain-specific to
   the tuning agent, not generic LLM transport. Moving them to the tuning agent would make
   the bridge a pure transport layer (`generate`, `generate_text`, `list_models`), which
   is cleaner and more consistent with how all other nodes use the bridge.

2. ~~**Provider name for the unified client**~~: Resolved in 1.1. `provider` is now a
   routing label used to look up defaults from `_KNOWN_PROVIDERS`. Unknown provider
   strings are accepted — they just require explicit `base_url`/`api_key`/`model_id`.

3. **Gemini-specific behaviors**: `json_object` response format and plain-text mode both
   verified working via the OpenAI-compat endpoint with `gemini-2.5-flash` and
   `gemini-3.1-flash-lite-preview`. Still need to verify `gemini-3.1-pro-preview` (used
   by the implementor node).
