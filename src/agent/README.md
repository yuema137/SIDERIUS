# `agent/` — LLM access, prompt surfaces, and the agents' atomic tools

**Start here if you are integrating provider access, prompt rendering, or an
agent skill.**
**Authority**: the source. Template:
[`docs/agent-reference/MODULE_README_TEMPLATE.md`](../../docs/agent-reference/MODULE_README_TEMPLATE.md).

## Purpose

Everything the nodes *share* in order to be agents: the provider-agnostic LLM
transport, the prompt templates and their task-block adapters, the typed node
contracts and protocols ([`agent/schemas/`](schemas/README.md), its own map),
and the atomic tools ("skills") agents call internally. No node lifecycle
logic lives here — that is [`nodes/`](../nodes/README.md) — and nothing here
executes training, inference or scoring.

## Public interface

| file | surface |
|---|---|
| `llm_bridge.py` | `LLMBridge` — every provider is accessed through the OpenAI SDK. Known providers `openai` / `gemini` / `deepseek` resolve `base_url` + key env var automatically; **any OpenAI-compatible endpoint** works via explicit `base_url`/`api_key`. Also the `reflect_provider` split (route the reflector to a second provider/model) and the stub-mode bridge for $0 pseudo runs |
| `prompts.py` + `prompt_templates/` | per-node prompt rendering (`proposal/`, `implementor/`, `interpretation/`, `tuner/`, `literature_review/`). Task science enters ONLY as caller-supplied task-blocks values parsed by `prompt_templates/_task_blocks_loader.py` — the shared mechanics of the three adapters (proposal / implementor / interpretation) |
| `schemas/` | node input/output contracts and the typed edge protocols — see [`schemas/README.md`](schemas/README.md) |
| `skills/` | atomic tools invoked by agents: `training_skill`, `inference_skill`, `denoising_score_skill`, `evaluate_time_skill` (+ the `~/.siderius` calibration store), `evaluate_vram_skill`, `check_config_format_skill`, `model_io_probe_skill.py`, `forbidden_pattern_skill.py`, `paper_resolver_skill` |
| `tools_schema.py` | `load_skills_from_library` — scans `skills/` for `skill_config.json` declarations |
| `cache_consolidator.py` | LLM-powered semantic consolidation of the model-knowledge cache's two accumulating list fields |
| `utils/` | `architectural_pattern_tagger.py` (closed-vocabulary structural tags for proposals) · `proposer_preflight.py` (pre-implementor wall-time risk signal) |

## Inputs

API keys from the environment (`OPENAI_API_KEY` / `GEMINI_API_KEY` /
`DEEPSEEK_API_KEY`; `LLMBridge` calls `load_dotenv()`, so a repo-root `.env`
works); per-stage routing from `configs/llm/*.json`
(`workflows/llm_config.py` loads them); task-block YAML paths supplied by the
caller, never discovered.

## Outputs

Validated Pydantic payloads. **No raw LLM output crosses into execution** —
every generated config or plan passes its schema before any downstream module
reads it (CLAUDE.md binding rule).

## Owned semantics

- **Retry classification** (`LLMBridge._call_with_retry`): 429 and 5xx are
  retried — by default indefinitely, which is deliberate (an exhausted quota
  waits for a top-up and the chain resumes); timeouts and connection errors
  carry their own **bounded** budget; every other 4xx (bad key, unknown
  model) is **raised immediately** — it will not heal on retry.
- **Prompt byte-surfaces are pinned.** The planner/reflector prompt bodies
  are guarded by exact renders in tests; a template edit is a semantic change
  with its own gate obligations, not a copyedit.
- **Task declarations are caller-owned, not template-owned.** Templates render
  framework structure; task-block *values* arrive from the composition caller
  (absent ⇒ nothing rendered). A retained illustrative example in
  `prompt_templates/literature_review/__init__.py` is neither a default nor
  scientific authority. Census guards cover the framework-owned template
  surfaces; they do not turn retained illustrative text into task defaults.

## Non-owned semantics

- When an agent is called, retries at the *node* level, round policy → the
  node (`nodes/`).
- What flows between nodes → [`schemas/`](schemas/README.md) protocols.
- Deterministic execution (training/inference/scoring) →
  [`execute_tools/`](../execute_tools/README.md) via `core/sandbox_executor`.
- Which provider serves which stage in a real run → `configs/llm/*.json`
  routing, an operator artifact.

## Extension points

- **A new LLM endpoint needs no code** when it is OpenAI-compatible: pass
  `base_url` and `api_key` explicitly (or route via `configs/llm/*.json`).
  The `_KNOWN_PROVIDERS` table is convenience defaults, not a gate.
- **New task science** for the proposer/implementor/interpreter is a
  task-owned blocks YAML named by the composition manifest — no template
  edit, no new adapter.
- A genuinely new atomic tool is a new `skills/` package with a
  `skill_config.json`.

## State and filesystem effects

Real bridges spend money and log per-call telemetry rows; the time-estimation
skill appends observations to the `~/.siderius` calibration store. Stub mode
touches neither network nor disk. Nothing here writes into the repository
checkout.

## Failure modes

| refusal | meaning |
|---|---|
| `ValueError: Unknown reflect_provider …` | a reflect route names a provider with no known defaults — supply `base_url`/`api_key` |
| immediate raise on 4xx (e.g. HTTP 401) | wrong or revoked API key; the bridge does not retry it |
| `[LLMBridge.…] N attempts timed out …; raising` | the bounded timeout budget working — raise `request_timeout`, do not loop |
| schema `ValidationError` after a call | the model's payload failed the node contract; content-level retry policy applies before the node sees it |

## Files normally edited

Task-block adapter *loaders* only alongside their design docs; `skills/`
packages under their own contracts. Routing changes belong in
`configs/llm/*.json`, not in `llm_bridge.py`.

## Files normally NOT edited

`llm_bridge.py`'s retry policy (the unbounded 429 retry is a design decision,
not a bug); the prompt template bodies (byte-pinned; see Owned semantics);
`schemas/` field shapes without walking the node checklist.

## Minimal example

```python
from agent.llm_bridge import LLMBridge
bridge = LLMBridge(provider="openai")           # key from OPENAI_API_KEY / .env
text = bridge.generate_text(system_prompt="…", user_prompt="say ok")
```

## Related tests

`tests/unit/agent/` (per-node prompt and schema suites, bridge behaviour,
skills); prompt-surface pin tests under the node suites; dual-mode
integration tests exercise the stub bridge by default; see the
[pseudo-full-loop testing guide](../../docs/architecture.md#pseudo-full-loop-tests).
