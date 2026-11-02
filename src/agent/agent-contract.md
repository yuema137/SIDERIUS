# `agent/` — LLM access, prompt surfaces, and the agents' atomic tools

Technical inventory for this module. Start with [the directory guide](README.md)
for navigation. Source and tests determine current behavior.

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
| `llm_bridge.py` | `LLMBridge` — default OpenAI-compatible transport plus optional Pydantic AI Direct API adapters. Supported providers resolve `base_url` + key env var through `llm_settings.py`; the [installation table](../../docs/getting-started/installation.md#api-keys) specifies which require explicit model selection; **any OpenAI-compatible endpoint** works via explicit `base_url`/`api_key`. Also the `reflect_provider` split (route the reflector to a second provider/model) and the stub-mode bridge for $0 pseudo runs |
| `llm_transport/` | Optional provider adapters; [transport contract](llm_transport/transport-contract.md) owns selection, protocol translation, limitations and validation |
| `credential_environment.py` | `load_compatibility_dotenv` (python-dotenv default search, `override=False`; logs the loaded path once per process at INFO and warns when it is outside the checkout or group/other-accessible) and `warn_if_blank_credential` (warns by name for a set-but-blank key). Logs paths, modes and names only, never values |
| `llm_settings.py` | Pure provider/model/timeout and reflector-inheritance resolution used by the bridge and offline inspection; no credentials or client construction |
| `prompts.py` + `prompt_templates/` | per-node prompt rendering (`proposal/`, `implementor/`, `interpretation/`, `tuner/`, `literature_review/`). Task science comes from validated task declarations: task-block values parsed by `prompt_templates/_task_blocks_loader.py` and the composed evaluation context rendered by `evaluation.spec`. The loader remains the shared owner for the proposal / implementor / interpretation block adapters |
| `judge/` | LLM judge call/evidence core: one bounded `run_judge_call` through `LLMBridge`, write-once `JudgeCallEvidence`, provider-free replay; see the [judge contract](judge/judge-contract.md) |
| `schemas/` | node input/output contracts and the typed edge protocols — see [`schemas/README.md`](schemas/README.md) |
| `skills/` | atomic tools invoked by agents: `training_skill`, `inference_skill`, `denoising_score_skill`, `evaluate_time_skill` (+ the `~/.siderius` calibration store), `evaluate_vram_skill`, `check_config_format_skill`, `model_io_probe_skill.py`, `forbidden_pattern_skill.py`, `paper_resolver_skill` |
| `tools_schema.py` | `load_skills_from_library` — scans `skills/` for `skill_config.json` declarations |
| `cache_consolidator.py` | LLM-powered semantic consolidation of the model-knowledge cache's two accumulating list fields |
| `utils/` | `architectural_pattern_tagger.py` (closed-vocabulary structural tags for proposals) · `proposer_preflight.py` (pre-implementor wall-time risk signal) |

## Inspect transport settings without calling a provider

```python
from agent.llm_settings import resolve_main_transport, resolve_reflect_transport

main = resolve_main_transport(provider="openai", model_id="your-model-id")
reflect = resolve_reflect_transport(main, model_id="your-reflector-model-id")
print(main.request_timeout, reflect.reuse_main_client)  # 600.0, True
```

These functions resolve the same transport choices used by `LLMBridge` without
loading dotenv, reading keys or creating clients. They do not resolve a node's
routing, validate provider access or prove that a model exists. An endpoint of
`None` means the SDK/environment chooses the destination. An omitted reflector
model inherits the main model even when its provider differs; supply the model
explicitly when selecting a different provider.

## Inputs

API keys from the environment; the
[installation provider table](../../docs/getting-started/installation.md#api-keys)
owns credential names and default-model versus explicit-model requirements.
`LLMBridge` calls `load_compatibility_dotenv()`, so a repo-root `.env` works
under the [compatibility loading rules](../../docs/getting-started/installation.md#compatibility-env-loading).
Per-stage routing comes from `configs/llm/*.json`
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

- **An OpenAI-compatible endpoint** can use explicit bridge `base_url` and
  `api_key` arguments. Workflow routing accepts the declared `ProviderName`
  values; arbitrary endpoint configuration is not a workflow JSON field.
  `KNOWN_PROVIDERS` retains legacy defaults; `OPTIONAL_PROVIDERS` declares
  additional credential/endpoint metadata without inventing model defaults.
  `provider_configuration` is the combined metadata lookup, and
  `llm_bridge._KNOWN_PROVIDERS` remains a compatibility export.
- **Anthropic, Moonshot, and Z.AI** select the optional Direct API backend
  through `provider` and explicit `model_id`. Install the extra and follow the
  [adapter guide](llm_transport/README.md). Python callers can explicitly
  override transport protocol; see the [transport contract](llm_transport/transport-contract.md).
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
[workflow integration guide](../../tests/integration/workflows/README.md).

## Persisted prompt history decoding

Planner memory and reflector actual-results dictionaries are decoded through
`core.record_encoding.decode_record` at the prompt entry point, including
external raw-summary callers. Storage metadata is never prompt evidence.
Finite/null prompt bytes remain unchanged. Non-finite values retain the
existing numeric prompt-text rendering after decoding; historical null
records remain null. The detailed serialization/paper-impact owner is
[core record contract](../core/core-contract.md#raw-consumer-boundary-and-prompt-rendering).

## Structured evaluation declaration boundary

Task compositions may carry an opt-in `evaluation` declaration with component
meanings, quantitative selection and constraints, or rubric references. Composition validates and fingerprints the declaration.
The shared constraint
append path renders it through `evaluation.spec` using a scoped, copyable context.
The absent-spec gate is outside the boundary, preserving historical profile
admission and message bytes. Primary-only metric evaluation can launch; other
evaluation capabilities retain their own guards. Rubric judgment is
never arithmetic in MetricOrder; #1297 owns any new candidate-result projector and
versioned judge evidence. The exact schema and future Health/source-metric binding
are in the [evaluation contract](../execute_tools/evaluation-contract.md).

## Pseudo model tensor geometry

`StubLLMBridge` delegates implementor code and repair snippets to
`stub_model.stub_model_code`. For composed runs it acquires the validated
`ModelIOContract` through `workflows.task_config.run_bound_model_io_contract`.
The stub accepts numeric tensors without treating values as vocabulary indices.
It expands a differentiable scalar projection to the declared output: fixed
extents remain fixed, and shared symbolic extents are read from the corresponding
input axes at forward time. Batch size and symbolic sequence/row lengths are
therefore not frozen to smoke-test sizes. The projection is a plumbing witness,
not a scientific architecture or a useful predictor.

An output extent that is neither fixed nor shared with the input raises
`UnsupportedStubShapeError`, identifying the unresolved output axis before
plugin execution. Unbound bridge fixtures and legacy prose-only declarations
retain the historical 256-token sequence stub.

The projection is cast to the first floating dtype in the output contract's
`admissible` order (`float16`, `bfloat16`, `float32` or `float64`) and
materialized with `.contiguous()`, so in-place or `.view` loss steps see owned
storage rather than an expanded alias. An output contract with no floating
admissible dtype raises `UnsupportedStubShapeError` from `stub_model_code`,
naming the declared dtypes, before candidate execution or the smoke/repair loop.
The unbound legacy stub is unchanged.

`stub_model.stub_proposal_semantics` derives the pseudo proposal from the same
bound contract (`stub_model.bound_stub_contract`). `output_type` is the
contract's `legacy_output_type`; the baseline and tuner-planner `loss_type` is
`ce` for a categorical output and `smooth_l1` for a continuous one, so both pass
`validate_semantic_loss_compatibility` and the candidate probe sees the declared
geometry. The model description, mathematical definition, motivation, expert
advice constraint, comparison/causal mechanism and proposer/implementor
reasoning describe the emitted scalar projection, rendered input and declared
output shape with the emitted dtype. No task name is consulted. An output with no
floating admissible dtype raises `UnsupportedStubShapeError` already at proposal
synthesis. Unbound fixtures keep the historical sequence narrative, `classifier`
and `ce` unchanged.

`stub_model.py` is outside the `rendering_assembly_digest` and planner strategy
source closures: it produces pseudo plugin bytes, not prompts. Edits confined to
it change explicit-contract pseudo plugin bytes and their downstream artifact
identities, but not those assembly identities. Edits to `StubLLMBridge` in
`llm_bridge.py` still change both closures. Real provider calls, prompt
templates and task declarations are unaffected. Resume/preflight identity checks
remain strict.

`tests/unit/agent/llm_bridge/test_stub_task_shapes.py` covers negative float
inputs, image classification, sequence classification, row classification and
continuous tensor outputs through candidate validation and forward/backward
execution with changing runtime extents. Passing these checks establishes model
shape compatibility; it does not establish that downstream pseudo training or
resource admission supports a task or host.
