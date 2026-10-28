# `agent/judge/` — LLM judge call and evidence core

Technical contract for the judge call/evidence core (advanced design B2, PR
B2-1). Source and tests determine current behavior. The first production
consumer is JudgeStop (`tools/candidate_worker/loop_judge.py`, candidate-worker
contract "Judge stop condition"); LLM COMBINE strategies (`rubric-rank/v1`, B2-6)
call it through `workflows/judge_strategies/`
([strategy contract](../../workflows/judge_strategies/judge-strategies-contract.md)).

## Scope and owners

| Owner | Responsibility |
| --- | --- |
| [`agent/schemas/judge.py`](../schemas/judge.py) | Typed records: `CallContent` (`StopJudgeRequest` kind `stop`; `RubricScoringRequest` kind `rubric_scoring` with `JudgedItem`/`ItemProjection`/`ProjectedField`; `MergeRequest` kind `merge`; `AdviceRequest` kind `advice`; `RevisionRequest` kind `revision`; `AdvocacyRequest` kind `advocacy`; `CritiqueRequest` kind `critique`; `DebateVerdictRequest` kind `debate_verdict`), `JudgeBodyFacts`, `DirectionWords`, `CallRequest`, `CallPayload` (`StopVerdict` kind `stop_decision`; `RubricVerdict` kind `rubric`; `SynthesisVerdict` kind `synthesis` with `SynthesizedDraft(parents, value)`; `AdvisoryNote` kind `advice`; `DebateTurn` kind `debate_turn`; `RankVerdict` kind `rank`), `PromptIdentity`, `JudgeRoute`, `JudgeCallEvidence` |
| [`template.py`](template.py) | `JudgeTemplate`: one versioned, framework-owned template per call role; pure rendering and `PromptIdentity` |
| [`stop_template.py`](stop_template.py) | `STOP_TEMPLATE` (`judge.stop/v1`, usage label `judge.stop`, response model `StopVerdict`) |
| [`rubric_template.py`](rubric_template.py) | `RUBRIC_TEMPLATE` (`judge.rubric/v1`, role `scorer`, usage label `judge.rubric-rank`, response model `RubricVerdict`, `check_payload`: exactly the listed items and rubric criteria, integers within the scale) |
| [`call.py`](call.py) | `run_judge_call` — the only function in the package that contacts a provider; `emit_judge_marker` (best-effort usage marker row for a skipped call through the bound bridge's `emit_marker`; no provider call, no evidence, no deadline check, never raises an `Exception`); `JudgeRunContext`, `JudgeCallRefused`, `JudgeEvidenceConflict` |
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
`MetricOrder.direction_words` by the consumer and validated for coherence;
this package never reads a metric direction. `StopJudgeRequest` refuses
incoherent facts:

- the final boundary is never judged (`iteration < final_iteration`, Q-B2-6);
- bodies are strictly increasing and end at `iteration`;
- `non_improving_bodies <= len(bodies)`;
- the incumbent is set exactly when some body is ranked, and then names a body
  with `rank == 1` and the same value (`incumbent_iteration`, `incumbent`);
- `interpretation_digests` and `interpretation_excerpts` pair one-to-one, with
  at most one excerpt per completed body, each at most 2000 characters.

`CallRequest` is the hashed identity of one call: `invocation_sha256`,
`call_role`, `call_index`, `prior_turns` and `content`. `content` is the
discriminated union `CallContent` keyed by `kind` (`StopJudgeRequest`,
`kind="stop"`; `RubricScoringRequest`, `kind="rubric_scoring"`; `MergeRequest`,
`kind="merge"`; `AdviceRequest`, `kind="advice"`; `RevisionRequest`,
`kind="revision"`; `AdvocacyRequest`, `kind="advocacy"`; `CritiqueRequest`,
`kind="critique"`; `DebateVerdictRequest`, `kind="debate_verdict"`); further strategy
content kinds join the union in their own changes without changing the bytes of
existing requests. The role must be one admitted for the content kind (`stop` →
`call_role="stop"`; `rubric_scoring` → `call_role="scorer"`; `merge` →
`call_role="merger"`; `advice` → `advisor`; `revision` → `reviser`; `advocacy` → `advocate`; `critique` → `critic`;
`debate_verdict` → `judge`). A stop
call is a single call: `invocation_sha256 is None` and `call_index == 0`; every
other content kind names its invocation. `prior_turns` must list the
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
digest of the response model's JSON schema). Template text, the rendered
prompt for a fixture request, the fixture `request_sha256` and the
response-schema digest are pinned by exact-digest tests. The schema digest
depends on Pydantic's JSON-schema output, so it is part of the template
version: a wording, response-model or Pydantic change that moves any pin needs
a new template version (existing evidence then no longer replays against the
new template).

`JudgeTemplate.check_payload(request, payload) -> str | None` is an optional
request-aware admissibility check (for example, a ranking that must be a
permutation of the request's admissible items). It runs on a schema-valid
payload; a returned message makes the call `inadmissible_choice`.

## The call (`run_judge_call`)

Inputs: `request`, `template`, `route: JudgeRoute`, `context`,
`evidence_path`, required `max_calls`, optional `bridge_factory` (default
constructs `LLMBridge` from the route).

1. Refuse with `JudgeCallRefused`, before any provider contact and without
   writing, when: the stop request's `iteration` differs from
   `context.iteration`; `max_calls <= 0` or `request.call_index >=
   max_calls`; `evidence_path` already exists (evidence is never reused); the
   bridge cannot be constructed (for example a missing credential); or
   `set_run_context` fails. The last two carry the original exception as
   `__cause__`. An execution deadline that has already expired is not a
   refusal: `ExecutionDeadlineExceeded` propagates unchanged from the
   pre-request checkpoint, nothing is written, and no provider is contacted,
   so callers keep classifying deadlines by exception type.
2. The bridge is bound with `set_run_context(workspace, iter, run_name,
   run_id)`, so the call's rows land in the run's `token_usage.jsonl` under
   label `template.usage_label`.
3. One `bridge.generate(system, user, label=...)` invocation. Its provider
   attempts are finitely bounded: up to `1 + LLMBridge._CONTENT_RETRY_BUDGET`
   content attempts (empty/non-JSON bodies), each with up to
   `JudgeRoute.max_retries` 429/5xx retries plus the bridge's own bounded
   timeout/connection retries. `max_retries` and `max_output_tokens` are
   required, so the bridge's unbounded 429 default never applies.
   `request_timeout` and `timeout_retries` use bridge defaults and are not
   part of the route identity recorded in evidence.
4. Validate the returned JSON with `response_model.model_validate_json`
   (strict, `extra="forbid"`); a non-object return (string, array) fails
   validation. Nothing unvalidated is recorded as a payload. Then run
   `check_payload` if the template declares one.
5. Publish `JudgeCallEvidence` once with `publish_bytes_write_once` as canonical
   JSON, and return it.

Failures after admission are recorded, not raised: `TimeoutError` (including
`ExecutionDeadlineExceeded`) during the call → `status="timed_out"`,
`failure_code="deadline"`; any other bridge exception →
`failed`/`provider_error`; a schema `ValidationError` →
`failed`/`invalid_payload`; a `check_payload` message, or an exception raised
by `check_payload`, → `failed`/`inadmissible_choice`. `failure_message` is the exception type and
text (or the check message), truncated to 2000 characters. The consumer
applies its declared failure policy (default: fail).

Single writer per path: the caller assigns each evidence path to exactly one
call. The existence check in step 1 and the publish in step 5 are not atomic;
if another writer publishes first, `JudgeEvidenceConflict` is raised after the
provider call (its usage rows remain recorded) and the record is not published.
No exclusive pre-claim is made.

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
   to be the template's response model and, when the template declares
   `check_payload`, a decided payload to still pass it.

The returned evidence is the call's outcome; replay equals the recorded run.
`verify_call_chain(evidences)` requires one invocation, one content kind,
`call_index` equal to position and `prior_turns` covering every earlier call,
so calls cannot be reordered, dropped or spliced. Roles may differ within a
chain (a debate mixes advocate, critic and judge calls); a stop call is always
a one-call chain. Any mismatch raises `JudgeEvidenceError`.

## Validation evidence

`tests/unit/agent/judge/test_judge_call.py`: pinned request, template, prompt
and response-schema digests; replay equality; foreign request/schema/route
refused; payload edit refused by the anchor digest; reordered or spliced chain
refused; failure classes (including non-object returns and
`inadmissible_choice`) published and replayable; admission, existing-evidence
and bridge-setup refusals before a call; incoherent stop facts (including the
final boundary) refused; usage row label and run id through a real `LLMBridge`
with a mocked client; AST guard that readback modules import no bridge.

## Limitations

- Content kinds exist for every call role of the four strategy kinds and the stop
  judge. The `judge.merge/v1`, `judge.advice/v1`, `judge.revision/v1` and
  `judge.debate.*/v1` templates live in `workflows/judge_strategies/` because
  their payload checks resolve the output contract's native type.
- Route resolution: `workflows.llm_config.judge_route` / `locked_judge_routes`
  convert `WorkflowLLMConfig.judge` into `JudgeRoute`/`JudgeRoutes`, which the run
  lock records canonically (`RunInvariants.judge_routes`, including the run-level
  `max_judge_calls` cap). Consumers enforce the cap (JudgeStop: candidate-worker
  contract).
- Task judge guidance text is not rendered by `judge.stop/v1`; JudgeStop therefore
  records `task_guidance_sha256=None`. Rendering guidance needs a new template
  version.
