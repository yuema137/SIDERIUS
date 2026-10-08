# Semantic snapshot review API

## Scope and authority

`tools.setup_review.semantic_review.review_snapshot(SemanticReviewRequest)` returns
`SemanticReviewReceipt` and writes a new local receipt/HTML directory. The adjacent
`SKILL_SPEC` uses the same concrete `SemanticReviewRequest` BaseModel, whose
`operation` field discriminates review and skip. Its generated tool schema has
an object root. There is no registry, node graph or alternate assistant parser.
The CLI is `python -m tools.setup_review.review --request <operation.json>`.

The accepted source schemas are `siderius.setup-declaration/v2` and
`siderius.task-composition-check/v1`. Original reports remain untouched.
For task checks, `SavedTaskCheckSnapshot` validates the exact schema discriminator,
typed declaration, `CompositionResult` and limitations. It explicitly ignores
unused historical request/job/sandbox/runtime/execution wrappers. The entire
source file remains digest-bound, but those wrappers are neither used nor fully
validated. In particular, it never constructs a live `SandboxProfile` or checks
old scratch/source/device paths. This typed projection preserves its consumed
facts without claiming the historical sandbox can still launch. Malformed consumed
fields and missing/incorrect schema discriminators are refused.
No task/plugin/data/model/Health/hardware execution occurs. The saved standard
single-iteration scope cannot represent arbitrary orchestration or run_chain.
Existing launchers, default routes and experiment prompts are unaffected.

```python
from tools.setup_review.semantic_models import SemanticReviewRequest
from tools.setup_review.semantic_review import SKILL_SPEC, review_snapshot

request = SemanticReviewRequest.model_validate(operation_json)
tool_definition = SKILL_SPEC.to_openai_tool()
receipt = review_snapshot(request)
```

`operation_json` is the outer object containing `operation`, as shown in the
[human guide](README.md#ask-for-an-optional-llm-review-or-explicitly-skip-it).
Calling the function with review kind can spend API credits; schema inspection
and skip do not construct the gateway. Permission/budget for actual external
calls belongs to the caller; installing this API grants neither.

## Boundaries and state

- Both operations require the selected report's absolute path, expected SHA-256,
  positive explicit `input_max_bytes`, and fresh canonical absolute output path.
  `core.file_identity` supplies no-follow/nonblocking open and regular-file checks;
  the same descriptor supplies bounded bytes and pre/post metadata. The actual
  bytes must match the requested digest. No returned source path is followed.
- Output admission refuses existing directories, symlink aliases, overlap with
  the report/run workspace/installation, or missing parents. The caller controls
  directory ancestors; this is not protection against hostile concurrent same-user
  replacement. `core.durable_io` publishes files write-once; the page is last.
  No recursive cleanup or overwrite is attempted on failure.
- Skip requires a nonblank reason. It preserves the old report's not_performed
  state and saves a new skipped receipt. No provider/module/credential access is
  needed. The selected semantic packet is still saved locally.
- Review takes existing `NodeLLMConfig`, with finite nonnegative `max_retries`,
  positive finite total-review seconds and request timeout. Existing node kwargs
  and transport resolvers own meaning/defaults. There is no implicit selection
  of an experiment node as the reviewer.
- One cooperative `execution_deadline` begins before reading the report and is
  retained through packet IO, lazy gateway import/construction and all requests/
  retries/response validation. Boundary checks reject expired work. It cannot
  interrupt blocked parent IO or force a hard wall-time/dollar cap. Final diagnostic
  publication can itself block or fail; receipt timing describes the checked
  outcome before those final writes, not a hard transaction deadline.
- Only the review branch lazily imports `semantic_llm` and `agent.llm_bridge`.
  Public `LLMBridge.generate` is called once with label `setup_review.judge`.
  Content retries, transport retries, dotenv behavior and telemetry stay owned
  by the bridge. Its context uses this review directory, a unique review run ID
  and iteration0. One generate invocation may produce multiple provider calls.
- Response JSON is validated with `SetupJudgement`. There is no additional model
  repair loop. Every finding has severity, field, explanation, suggested correction
  and uncertainty; uncovered checks remain separate. A schema-valid answer is
  advisory and never overrides deterministic failure.
- Provider/schema/timeout failures after packet preparation produce failed receipts
  where publication succeeds. Exception values are not copied into receipts.
  Input/IO failures before a usable output may raise; the CLI exits2. Reviewed and
  skipped return0. No success is printed before final page publication.

## Transmission and provenance

`semantic_packet` is a transmission allowlist, not a configuration resolver.
Named scalar CLI rows retain saved default/declared values. Typed model routes,
key-name statuses and unresolved checks are projected without raw argv or raw
declared_llm_config. Task snapshots project named metric/forward-contract fields,
partition count, named rule values, inference policy and Health declaration.
Nested rule values or arbitrary task/config fields not handled by the allowlist
are omitted, not interpreted. Packet coverage explicitly names exclusions.

Raw advice, file contents, exception details, sandbox environment and scratch
paths are not transmitted. Allowed free text may still contain secrets or malicious
instructions. The system prompt treats it as untrusted data; the judge gets no
tools. This is not an automatic secret detector or a prompt-injection guarantee.
The operator must inspect selected content before enabling a call and before
publishing reports. Ambient credential values are never serialized by this API.

The review writes exact system/user prompt bytes before calling the provider.
Receipt hashes bind source report, packet and prompts; prompt version is
`setup-review/v1`. Prepared prompt files do not establish that a request was sent.
The bridge writes available usage/served-model evidence to its normal token log;
telemetry absence does not prove zero usage. The receipt records its filename
only if present, never fabricates a served-model identity or total cost.

Snapshot identity is not a complete task/environment closure. Editing task files
after the earlier report is not detected here. A future explicitly selected
reviewed-launch adapter must resolve current owner facts and bind freshness;
ordinary launchers have no new gate. Paper compatibility settings remain exp-owned.

## Verification expectations

CPU tests exercise actual report loading, FIFO/no-follow refusal, digest and byte
limits, actual callable/CLI publication, cold skip imports/environment access,
fake public gateway arguments/prompts/telemetry context, preparation/constructor/
response/validation deadlines, malformed responses and retained deterministic
failure. HTML escapes all user/model text. Partial publication never replaces a
concurrent file. Real provider quality, authentication, costs, GPU behavior and
four independent onboarding runs require separate authorized qualification.
