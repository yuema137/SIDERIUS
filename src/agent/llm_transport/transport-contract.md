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
| `tool_admission.py` | Shared complete single-tool admission for legacy and Direct API routes |
| `responses.py` | Admit complete representable results and normalize measured usage |
| `background.py` | OpenAI background mode: window admission, poll loop, cancellation, submission ledger row and pricing evidence |
| `LLMBridge` | Retry policies, remaining-deadline clipping, content repair, labels and usage persistence |

## Selection, credentials, and configuration

Default routes for `openai`, `gemini`, and `deepseek` retain the existing OpenAI
SDK Chat Completions implementation. New providers automatically select this
backend when specified through workflow `provider` and `model_id` fields.

Credential names and model-selection requirements are owned by the
[installation provider table](../../../docs/getting-started/installation.md#api-keys).

| Provider | Default endpoint | Default protocol/model adapter |
| --- | --- | --- |
| `anthropic` | `https://api.anthropic.com` | Anthropic Messages / `AnthropicModel` |
| `moonshot` | `https://api.moonshot.ai/v1` | OpenAI-compatible Chat / `MoonshotAIProvider` |
| `zai` | `https://api.z.ai/api/paas/v4` | OpenAI-compatible Chat / `ZaiModel` |

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
that an arbitrary endpoint/model combination implements it. The one workflow
path to this carrier is `NodeLLMConfig.openai_background`, which selects
`openai-responses` with background mode for that route only (see
[OpenAI background completion windows](#openai-background-completion-windows)).

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

### Legacy single-tool admission

The default OpenAI-compatible `tool_call` route uses the same count, declared
name, nonempty call ID and complete JSON-object argument checks as Direct API.
It additionally requires exactly one response choice, a function call, no
refusal, and a complete SDK `stop` or `tool_calls` finish reason. Invalid
responses raise `ValueError` after billed usage is recorded, outside retries.
A continuing deadline takes precedence over admission and records one late
receipt. Valid requests and `ToolCallResult` payloads are unchanged. These
checks do not add argument-schema validation or tool execution.

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

## OpenAI background completion windows

`PydanticTransportConfig.background` (`OpenAIBackgroundConfig`:
`completion_window` `2h` | `8h`, required finite `max_wait_seconds > 0`) opts one
route into Responses API background mode. It requires `protocol="openai-responses"`
(schema refusal) and provider `openai` (`optional_client` refusal). It is excluded
from serialization when unset. Without it every request path is unchanged.
Provider facts used here (OpenAI background guide, 2026-11-18): the window is a
completion target from acceptance, not a guarantee; eligible models are in public
beta (GPT-6.2 Astra, GPT-6.2 Sol, GPT-6.1 Terra, GPT-6 Luna); 2h/8h share the
Batch/Background rate limit; prompt-cache entries from these windows are not
reusable by non-window Standard requests.

**Submission.** The create request carries `background: true`,
`service_tier: "default"` (Standard processing, which the discount requires),
`background_options: {"completion_window": ...}` via `extra_body` (the locked
OpenAI SDK has no typed field) and `stream: false`. It runs inside
`LLMBridge._call_with_retry` exactly like a foreground request: 429/5xx retries
(unbounded 429 by default), bounded timeout/connection retries and the
other-4xx immediate raise are unchanged. An unsupported model or setting is a
provider 4xx and raises immediately. A response already terminal at creation is
normalized directly; a pending one returns a `BackgroundTicket`.

**Admission.** Before submission, if a cooperative `execution_deadline` is
visible to the bridge and its remaining time is shorter than the window
(7200 s / 28800 s), `BackgroundWindowRefused` (an `ExecutionDeadlineExceeded`)
is raised and nothing is sent or billed. Inside a candidate worker the visible
deadline is the worker's remaining `timeout_seconds` (`WorkerBudget.deadline_scope`,
bound at every worker and graph-unit process entry; see the candidate-worker
contract), so a window longer than that remainder is refused there. Budgets no
caller binds as a deadline are not consulted; budget them for the summed waits
of sequential steps.

**Polling.** `finish_background` runs after `_call_with_retry` has returned, so
an accepted request can never be resubmitted by the transport retry owner. It
first appends a submission ledger row (below), then polls
`GET /v1/responses/{id}` through pydantic-ai continuation of the suspended
response. Cadence doubles from 2 s to a 60 s cap. Each GET is bounded by
`request_timeout` clipped to the remaining wait. Transient poll failures (HTTP
429/5xx, connection, timeout) are retried in place until the wait expires. A
404 (`SuspendedResponseExpired`) ends polling as a refused completion with
nothing to cancel. An undecodable body, a non-transient HTTP error (for example
400/403) or a failed response body first cancels the job (idempotent; an already
terminal job returns its final object), records the outcome as
`background_cancel`, then ends polling as a refused completion. A caller that
retries the step therefore never leaves the first job billing.

**Wait limit.** Expiry is `accepted_at + max_wait_seconds`, clipped by the
visible execution deadline when that is earlier. On expiry the response is
cancelled once (`POST /v1/responses/{id}/cancel`, best effort), its usage row is
recorded with `background_status: "wait_expired"`, `background_waited_seconds`
and `background_cancel`, and `BackgroundWaitExpired` (a `TimeoutError`, never a
transport error) is raised naming the route label, response id, completion
window, waited seconds and the binding limit (`max_wait_seconds` or
`execution_deadline`). When the execution deadline was the binding limit the
raised type is `BackgroundDeadlineExpired`, which is also an
`ExecutionDeadlineExceeded`, so deadline-aware callers report a deadline only
in that case. There is no implicit default wait.

**Terminal outcomes.** `completed` is admitted through the ordinary
normalization path. `failed`, `cancelled`, `incomplete` and the poll refusals
above are recorded once with whatever usage the provider reported and then
refused by `validate_completion` (`APIError`), outside retries. Content repair in
`_chat_json` still issues a new request (a new background submission) for
invalid JSON, within its existing bounded budget.

**Cancellation and stops.** Any in-process failure from the submission ledger
row through polling (a ledger write error, a deadline, KeyboardInterrupt,
asyncio cancellation, an unexpected exception) triggers one best-effort cancel
in `finish_background` before the exception propagates; a cancel failure never
masks the original exception. A response accepted just
before a continuing deadline expires is cancelled before the late receipt is
recorded. SIGTERM/SIGKILL of the process (candidate Stop, sandbox timeout,
scheduler kill) cannot run a cancel: the accepted response keeps running
server-side and is billed. Its submission row is the evidence for finding it.
When the bridge runs inside an existing event loop, the poll runs in a worker
thread and an interrupt in the calling thread does not reach it before the wait
limit. Resume does not reattach to a pending response; a resumed phase submits
a new request. If the create request is accepted but its response is lost (a
connection drop or timeout), the bounded timeout/connection retry submits again;
the first job keeps running with no ledger row because its id was never seen.
Foreground requests have the same exposure, without the background delay.

**Ledger rows.** At acceptance, `emit_marker` appends
`label="<call label>.background_submitted"` with zero tokens and characters and
`extra` = `{attempt, status: "background_submitted", model, provider,
background_response_id, completion_window, service_tier_requested: "default",
service_tier_served}`. The final row is the call site's ordinary usage row with
provider-measured token counts and the same evidence plus `background_status`
(the provider finish reason, e.g. `completed`). A submitted row without a final
row carrying the same `background_response_id` identifies an orphaned request.

**Cost.** Token counts stay exactly as the provider reports them. The framework
has no price table and records no USD figure. A cost consumer applies the window
rate (Standard model token rates times 0.7 for `2h`, 0.6 for `8h`) only when
`service_tier_served == "default"` and the model is eligible; otherwise it
applies the rate of the served tier. The response does not echo the window or
confirm a discount, so this rule is the contract.

**Reflector and stage isolation.** A reflector without its own transport never
reuses a background main client; the bridge constructs its default client.
Workflow projection never lets literature search or proposal stages inherit
another route's background carrier (see the workflow contract).

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
The native planner's `content_sha256` fingerprints `prompts.py`, while its
`assembly_sha256` also fingerprints bridge and transport sources. Admission-only
changes can therefore preserve content identity while refusing resume against
an older workspace assembly pin. Such changes require deliberate pin updates
in `tests/unit/agent/test_planner_strategy.py` and freeze-batch requalification;
run that test whenever `llm_bridge.py` changes. Do not rewrite archived pins.
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
