# Per-route retry transport contract

## Ownership

`LLMBridge._call_with_retry` remains the sole HTTP retry owner. `NodeLLMConfig.max_retries`
selects total attempts, including the first request, for transient 429/5xx and
connection/timeout errors. Existing values 0 and 1 both permit one request. None
leaves retryable status failures unbounded; the separate timeout/connection limit
still applies. This change does not modify existing integer/default semantics.

## Explicit overrides and inheritance

Workflow JSON continues to use the existing leaf `max_retries` field. Four
single-node routes and all three proposer routes already forward it. Literature
main now forwards it as `llm_max_retries`; literature search and tuner reflector
preserve field presence using the frozen `RetryPolicy(max_retries=...)` carrier.
No optional carrier means inherit the corresponding main/planner limit. A present
carrier whose value is None means explicitly unbounded status retries. A present
integer means that route's own limit. Pydantic validates the carrier at schema
boundaries; the bridge also validates JSON-projected constructor input.

`NodeLLMConfig` serialization omits only `max_retries` when the leaf field was
not supplied; other resolved defaults remain serialized. Explicit null remains
present. This preserves retry intent across Python/JSON round trips, saved setup
review snapshots and reviewed-launch identity comparisons. Effective route reports
separately show the inherited limit even when the declaration omits the field.

`WorkflowLLMConfig.get` creates an override only if the leaf field was supplied.
The tuner workflow, validator-to-tuner protocol and input schema retain it as
`reflect_retry_policy`. The bridge passes the selected policy directly into the
retry owner for `tuner.reflector`; it never temporarily mutates shared retry state.
The main and reflector may share a provider client while retaining separate limits.

Literature input carries `search_llm_retry_policy`. A search override alone creates
a separate bridge even if provider/model/effort have no override; explicit None
must not accidentally reuse a finitely limited main bridge. A retry-only split
retains the main reasoning effort; explicit search routing keeps its existing
independent reasoning defaults. If the complete
literature block is omitted, its existing interpretation fallback now forwards
an explicitly supplied interpretation retry limit too. No provider discovery,
installation or effect is added during projection.

## Defaults, reporting and scope

Configurations without explicit retry fields retain previous bridge kwargs and
unbounded status-retry defaults. New optional schema carriers serialize only
when present. Setup review uses the same constructor projection, reports resolved
per-route limits, and serializes carriers as JSON. The Luna smoke profile now sets
1 for both literature routes as well as the other nine routes.

This control does not cap JSON content repair, proposer corrections, implementor
repairs, workflow attempts, successful-round targets, tokens, prices or total wall
time. Their owners remain unchanged. Optional setup review and Data Analysis keep
existing cooperative deadlines; no global workflow deadline is added. Scientific
history is exp-owned: any bridge assembly change still requires final historical
profile qualification there, even if omitted-field call behavior is preserved.
