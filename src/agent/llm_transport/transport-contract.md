# Optional Direct API transport contract

## Scope and ownership

`LLMBridge` remains the only public model gateway. This package supplies its
optional Pydantic AI Direct API backend; it does not introduce another agent
loop, execute tools, or change scientific task semantics. Nodes retain the
existing `generate`, `generate_text`, `tool_call`, planner, and reflector APIs.

The dependency authority is `pyproject.toml` and `uv.lock`. The qualified
Pydantic AI Direct API release is 2.61.0. Its required SDK versions supersede
older SDK locks; preserving the legacy request path does not mean preserving
an older SDK binary. Compatibility evidence must cover the current lock.
The optional extra is `pydantic-ai`; dev dependencies include the same adapter
for offline CI. Legacy routes do not import Pydantic AI at runtime.

| Owner | Responsibility |
| --- | --- |
| `agent.llm_settings` | Provider names, endpoint/credential metadata, pure route resolution |
| `selection.py` | Select optional backend, validate output limit and configuration, refuse missing credentials |
| `contracts.py` | Frozen protocol configuration, private normalized response shape, post-accounting refusal |
| `client.py` | Synchronous facade with request-local asynchronous clients |
| `requests.py` | Translate complete system/user prompts and tool schemas |
| `providers.py` | Construct supported SDK/provider/model objects with SDK retries disabled |
| `runtime.py` | One Direct API request and exception translation |
| `accounting.py` | Raw JSON/SSE accounting capture before SDK defaults |
| `responses.py` | Admit complete representable results and normalize measured usage |
| `LLMBridge` | Retry policies, remaining-deadline clipping, content repair, labels and usage persistence |

## Selection, credentials, and configuration

Default routes for `openai`, `gemini`, and `deepseek` retain the existing OpenAI
SDK Chat Completions implementation. New providers automatically select this
backend when specified through workflow `provider` and `model_id` fields:

| Provider | Default endpoint | Credential variable | Default protocol/model adapter |
| --- | --- | --- | --- |
| `anthropic` | `https://api.anthropic.com` | `ANTHROPIC_API_KEY` | Anthropic Messages / `AnthropicModel` |
| `moonshot` | `https://api.moonshot.ai/v1` | `MOONSHOT_API_KEY` | OpenAI-compatible Chat / `MoonshotAIProvider` |
| `zai` | `https://api.z.ai/api/paas/v4` | `ZAI_API_KEY` | OpenAI-compatible Chat / `ZaiModel` |

New providers require an explicit model ID. Cross-provider reflector selection
also requires its own model ID for these providers. No model availability is
inferred from successful configuration parsing. Explicit bridge credentials
and endpoint overrides take precedence over provider defaults. Missing
credentials never fall back to a different provider's key. Setup review and
candidate admission inspect credential names through the shared metadata owner;
they do not authenticate with providers.

Python callers may pass `transport=PydanticTransportConfig(protocol=...)` to
`LLMBridge`. Supported protocol values are `anthropic`, `openai-chat`, and
`openai-responses`; `reflect_transport` can independently override the reflector.
For example, an OpenAI caller can explicitly select `openai-responses` while
keeping the same bridge methods. These protocol selectors are bridge constructor
options, not workflow JSON fields. They select a protocol rather than claiming
that an arbitrary endpoint/model combination implements it.

`max_output_tokens` is an optional positive integer output ceiling.
`reflect_max_output_tokens` overrides it for the reflector; omission inherits
the main ceiling. Workflow routing projects these values through its existing
node-specific argument mappings. Unset new schema fields are excluded from
serialization. Anthropic requests with no configured ceiling use 8192 output
tokens. This is an explicit backend default, not a model context limit or a
prediction based on input length. Provider/model-specific restrictions may
require another ceiling. Input prompts are never truncated by this adapter.

## Request and result semantics

The request contract is exactly one system message followed by one user message.
Translation retains the supplied prompt strings. Other message sequences are
refused. The Direct API call is `model_request`, with instrumentation disabled;
it is not a Pydantic AI `Agent` run.

- **Text:** request ordinary text. Accept nonempty text with a complete finish
  reason and no tool calls. Concatenate returned text parts in order.
- **JSON:** when the selected model profile declares JSON-object support,
  request that native mode through Pydantic AI `output_mode="prompted"`, an
  object output definition, and `prompted_output_template=False`. No extra
  JSON instruction template is appended. This is the route for supported
  Moonshot/GLM profiles. Otherwise translate the existing `json_object` request
  into one output tool named `siderius_json_result`, including Anthropic.
  Its argument is an object containing exactly
  `value`, whose value must be a JSON object or array. The tool is marked
  `strict=False`, `kind="output"`, and the request disallows text-only output.
  Normalize the returned `value` into the bridge's existing JSON parsing path.
  Native JSON text passes through the existing bridge JSON parsing/repair path.
  Result-tool conversion is a real wire-format change on that optional route; it is not native
  JSON-schema enforcement of a node's eventual business schema. Downstream
  Pydantic validation remains required.
- **Tool selection:** accept OpenAI-format function definitions and translate
  them into Pydantic AI `ToolDefinition` objects. Accept exactly one returned
  call to a declared tool, with a nonempty call ID and object arguments. Return
  the existing `ToolCallResult`; do not execute the tool.

Responses must have a complete `stop` or `tool_call` finish reason. Truncation,
refusal, unsupported content parts, absent/extra tool calls, undeclared tools,
and malformed result envelopes are refused after accounting. Thinking parts
are not returned by the one-shot public interface. Consequently this transport
does not provide a new multi-turn API, preserve continuation state for callers,
or claim support for thinking/tool round trips that need that state. Multiple
calls are rejected rather than silently selecting one.

The JSON result-tool strategy requires tool-capable models and support for the
requested tool/output mode. Some models or thinking configurations can reject
forced output-tool selection. There is no automatic fallback to prompt-only
JSON, another model, or another protocol. Qualification must exercise JSON and
tools separately for each intended model/configuration combination.

## Retry, lifecycle, and errors

Each invocation creates and closes its own asynchronous HTTP/SDK clients.
SDK retries are disabled. When called from an already running asyncio loop,
the synchronous facade runs the Direct API coroutine in a worker thread with
its own event loop; it does not expose asynchronous cancellation to callers.
The bridge supplies the remaining request timeout and checks the continuing
deadline after return.

Provider HTTP failures normalize to `openai.APIStatusError`, timeouts to
`openai.APITimeoutError`, connection failures to `openai.APIConnectionError`,
and other Pydantic AI model API failures to `openai.APIError`. This keeps the
existing bridge retry and tuner infrastructure-failure classification boundary.
Configuration/schema errors are not transient transport retries. The bridge
owns 429/5xx retry decisions, bounded timeout/connection attempts, reflector
retry overrides, and deadline-aware sleeping.

A returned but invalid normalized completion carries its refusal alongside
usage. `validate_completion` raises only after the bridge records that receipt;
this refusal is outside the transport retry loop. A response arriving after the
continuing deadline is accounted for once and then rejected. No tool or model
fallback is performed.

`list_models()` is explicitly unsupported on this backend and raises
`NotImplementedError`. Provider enumeration requires a separately implemented
contract; a Direct API request adapter does not establish one.

## Accounting and provenance

The HTTP response hook retains only raw `model` and `usage` fields from JSON or
SDK-internal SSE responses for local
normalization, not prompt or completion bodies. Provider-reported model identity
is distinct from the configured model ID. Missing reported identity remains
unknown. Missing usage remains unknown rather than taking Pydantic AI's default
zero counters as evidence of no consumption.

Supported raw count names are `prompt_tokens`/`completion_tokens` or
`input_tokens`/`output_tokens`. `total_tokens` is retained when supplied; otherwise
it is derived only if both component counts are present integers. Anthropic
cache-read and cache-creation input counts are added to its uncached input count. The existing
telemetry schema still owns persisted count fields. Cache/reasoning breakdowns
are not a new public accounting schema in this change.

Successfully normalized optional-route usage metadata records backend, Pydantic AI version, protocol,
effective output ceiling, and JSON mode (`object`, `tool`, or absent). This is
execution evidence, not a claim of endpoint authorization, exact reproduction,
or the ability to recover a multi-turn provider session.

The planner assembly identity includes `llm_bridge.py`, `llm_settings.py`, and
all Python sources beneath `llm_transport`, in addition to the existing prompt
owners. A transport or routing source change after preflight therefore refuses
the pinned planner identity before the provider request. Source identity does
not establish equivalence of live model outputs or qualify dependency upgrades.
This intentionally changes the assembly digest; existing run locks and archived
paper identities are not rewritten or treated as equivalent.

## Validation and scientific compatibility

Offline tests must exercise provider wire requests and response normalization,
public bridge reachability, old request parity, independent routes, credential
isolation, failures/retries, deadline/late receipts, missing usage, and current
SDK compatibility. Workflow routing tests cover propagation and unchanged
serialization when the new options are absent. Structural guards restrict
provider construction to the bridge and its declared adapter owner.

Anthropic, Moonshot, and Z.AI account access has not been established by these
offline tests; no live qualification with their credentials is claimed.
Model-specific availability, quotas, long-context limits, forced-tool behavior,
and scientific quality require explicit real-provider qualification.

This change does not edit deterministic data selection, training, scoring,
Health checks, or task plugins. Preserved legacy request/serialization behavior
is evidence against an unintended framework regression; it does not guarantee
bit-identical live LLM outputs or paper artifacts. Historical model/dependency
pins and experiment settings remain in the experiment repository.
