# `agent/judge/` — LLM judge call and evidence core

Technical contract for the judge call/evidence core (advanced design B2, PR
B2-1). Source and tests determine current behavior. Consumers (JudgeStop,
LLM combine/select strategies) are separate changes; this package has no
production caller yet.

## Scope and owners

| Owner | Responsibility |
| --- | --- |
| [`agent/schemas/judge.py`](../schemas/judge.py) | Typed records: `StopJudgeRequest`, `JudgeBodyFacts`, `DirectionWords`, `CallRequest`, `StopVerdict` (`CallPayload`), `PromptIdentity`, `JudgeRoute`, `JudgeCallEvidence` |
| [`template.py`](template.py) | `JudgeTemplate`: one versioned, framework-owned template per call role; pure rendering and `PromptIdentity` |
| [`stop_template.py`](stop_template.py) | `STOP_TEMPLATE` (`judge.stop/v1`, usage label `judge.stop`, response model `StopVerdict`) |
| [`call.py`](call.py) | `run_judge_call` — the only function in the package that contacts a provider |
| [`evidence.py`](evidence.py) | Readback: `read_call_evidence`, `verify_call_evidence`, `verify_call_chain`, `chain_prior_turns`, `evidence_sha256`; imports no bridge |

Not owned here: provider routing and usage rows (`LLMBridge`,
[agent contract](../agent-contract.md)); metric direction (`MetricOrder`);
Health classification; when a judge is called and what a failure means
(consumer `on_failure` policy); evidence path layout (consumer-assigned).

## Request content

A judge consumes facts produced by the deterministic core; it never scores.
`StopJudgeRequest` carries, per completed body, `JudgeBodyFacts(iteration,
value, rank, health)`; `value` and `rank` are set together and only when
`health == "valid"` (an INVALID/UNKNOWN body never presents a usable value).
Direction language is `DirectionWords(verb, comparative, antonym)`, built from
`MetricOrder.direction_words()` by the consumer and validated for coherence;
this package never reads a metric direction. The final boundary is never
judged (`iteration < final_iteration`).

`CallRequest` is the hashed identity of one call: `invocation_sha256`
(strategy calls; `None` for `call_role="stop"`), `call_role`, `call_index`,
`prior_turns` and the role-specific request. `prior_turns` must list the
`evidence_sha256` of every earlier call of the same chain
(`len(prior_turns) == call_index`). No timestamps or host facts enter a
request; run identity for usage accounting is the separate, unhashed
`JudgeRunContext(workspace, iteration, run_name, run_id)`.

## Rendering and identity

`JudgeTemplate.render(request)` is a pure function of the request: fixed system
text plus a user frame filled from the request, with facts as `json.dumps(...,
sort_keys=True, indent=2)`. A template refuses a request of another call role.
`PromptIdentity` records `template`, `template_sha256` (canonical digest of
id, role, usage label, system text and user frame), `prompt_sha256 =
canonical_sha256({"system", "user"})` and `response_schema_sha256` (canonical
digest of the response model's JSON schema). Template bytes are pinned by an
exact-digest test; a wording change is a new template version.

## The call (`run_judge_call`)

Inputs: `request`, `template`, `route: JudgeRoute`, `context`,
`evidence_path`, required `max_calls`, optional `bridge_factory` (default
constructs `LLMBridge` from the route).

1. Refuse with `JudgeCallRefused`, before rendering or any provider contact
   and without writing, when `max_calls <= 0`, `request.call_index >=
   max_calls`, or `evidence_path` already exists (evidence is never reused).
2. Render, then construct the bridge and bind `set_run_context(workspace,
   iter, run_name, run_id)`, so the call's rows land in the run's
   `token_usage.jsonl` under label `template.usage_label`.
3. `bridge.generate(system, user, label=...)` once. `JudgeRoute.max_retries`
   is a required finite integer and `max_output_tokens` is required, so the
   bridge's unbounded 429 default never applies to a judge call.
4. Validate the returned JSON with `response_model.model_validate_json`
   (strict, `extra="forbid"`); nothing unvalidated is recorded as a payload.
5. Publish `JudgeCallEvidence` once with `publish_bytes_write_once` as canonical
   JSON, and return it.

Failures are recorded, not raised: `TimeoutError` (including
`ExecutionDeadlineExceeded`) → `status="timed_out"`, `failure_code="deadline"`;
any other bridge exception → `failed`/`provider_error`; a schema
`ValidationError` → `failed`/`invalid_payload`. `failure_message` is the
exception type and text, truncated to 2000 characters. `inadmissible_choice`
is reserved for strategy consumers that check choices against an admissible
set. The consumer applies its declared failure policy (default: fail).

## Evidence invariants (`siderius.judge-call/v1`)

`request_sha256 == canonical_sha256(request)`; a payload exists exactly when
`status == "decided"`; a `failure_code` and `failure_message` exist exactly
when it did not decide; `timed_out` occurs exactly with `deadline`. The file
bytes equal `canonical_json_bytes(evidence)`, so `evidence_sha256(evidence)`
is the file digest.

## Readback without a provider

`verify_call_evidence(path, expected_sha256, request, template, route)`:

1. Read the file; its SHA-256 must equal `expected_sha256`, held by the
   referencing record (a later call's `prior_turns`, a stop reason or a
   strategy record). This is what pins the payload.
2. Parse strictly and require canonical bytes.
3. Require equality with the re-projected `request`, the re-rendered
   `PromptIdentity` (template, prompt and response-schema digests), the
   configured `route` and the template usage label; require the payload type
   to be the template's response model.

The returned evidence is the call's outcome; replay equals the recorded run.
`verify_call_chain(evidences)` requires one invocation, `call_index` equal to
position and `prior_turns` covering every earlier call, so calls cannot be
reordered, dropped or spliced. Any mismatch raises `JudgeEvidenceError`.

## Validation evidence

`tests/unit/agent/judge/test_judge_call.py`: pinned template/prompt digests;
replay equality with a provider spy; foreign request/schema/route refused;
payload edit refused by the anchor digest; reordered chain refused; failure
classes published and replayable; cap and existing-evidence refusals before a
call; usage row label and run id through a real `LLMBridge` with a mocked
client; AST guard that readback modules import no bridge.

## Limitations

- Only the stop call role has a request type and template; strategy roles
  (advocate, critic, scorer, …) gain request content, payload kinds and
  templates with their strategy changes.
- Task judge guidance (`task_guidance_sha256`) is carried as a digest only;
  rendering its text belongs to the task `judge_blocks` change.
- Run-level judge-call budgets and route resolution from workflow LLM
  configuration belong to the consumers and the judge routing slot.
