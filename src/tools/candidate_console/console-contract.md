# Local candidate console contract

Scope: single-user loopback console over public candidate_operations APIs. Native
request models, preparation/worker owners and native artifacts remain authoritative.
No provider construction, task composition, graph execution, scheduler, training,
source conversion, cancellation or secret editor belongs in this adapter.

## Configuration

`ConsoleConfig` and `TaskChoice` are strict/frozen Pydantic schemas. Configuration
is validated once at service startup. Example JSON (replace every resource path;
create the output roots before checking):

```json
{
  "operation_store": {
    "state_root": "/absolute/project/operation-state",
    "preparation_roots": ["/absolute/project/preparations"],
    "candidate_roots": ["/absolute/project/candidates"]
  },
  "tasks": [{
    "task_id": "my-task", "label": "My scientific task",
    "task_manifest": "/absolute/project/task.yaml",
    "data_root": "/absolute/project/data",
    "llm_config_file": "/absolute/project/llm.json",
    "task_read_only": [],
    "preparation_root": "/absolute/project/preparations",
    "candidate_root": "/absolute/project/candidates",
    "preparation_timeout_seconds": 120.0,
    "candidate_timeout_seconds": 600.0,
    "candidate_network": true,
    "candidate_devices": [],
    "candidate_environment_names": ["OPENAI_API_KEY"],
    "allowed_output_types": null
  }],
  "recorded_examples": [],
  "bind_host": "127.0.0.1", "port": 8740,
  "browser_origin": "http://127.0.0.1:8740",
  "auth_token_file": "/absolute/project/console-token",
  "credential_file": "/absolute/project/credentials.json"
}
```

Resource paths must be canonical and local, without symlinks. Output roots exist
inside registered operation roots; each browser preparation uses
`preparation_root/<operation UUID>` and `candidate_root/<operation UUID>`. Native
admission still owns runtime/source separation and exclusive absent-directory
claims. `check` validates inert file/configuration facts, not provider/task readiness.
Token and optional credential files are bounded, owner-only mode600 regular files;
private reads traverse no-follow directory descriptors. Token syntax encodes at
least 32 bytes; the operator must generate random bytes. Values never enter native
requests. Credentials are reread per launch and only configured native environment
names are passed; native environment validation rejects reserved names.
The credential file format is decided once, by `files.parse_credential_payload`,
on the bytes already read through that descriptor: a leading UTF-8 BOM is
ignored; first non-whitespace byte `{` means a strict JSON object of string names
to string values (`[` or `"` is refused as malformed JSON); anything else is
UTF-8 dotenv parsed by python-dotenv `dotenv_values(stream=..., interpolate=False)`
(no `${...}` expansion, no second open; names without a value are absent).
Undeclared entries are ignored and never logged. Parse refusals are raised
outside the parser's exception handler, so neither message nor chained cause
quotes bytes or values; missing declared names are reported by name only.

`recorded_examples` is an optional allowlist for read-only candidate-validation
records. Each entry has a unique `example_id`, readable `label`, canonical
`workspace` strictly below an existing `candidate_roots` directory, and the
expected 32-character lowercase `expected_run_id` from the native launch record.
The configured run ID protects against selecting another record at that path;
it is distinct from the candidate ID in the terminal receipt. The console
validates the fixed request, launch/terminal receipts, proposal, implementation,
validation and reported-token records before display. This does not import an
operation or infer process state. Missing captured source remains unavailable;
no training result, scientific score or billing cost is inferred.

```json
{
  "example_id": "tess-validation",
  "label": "TESS candidate validation example",
  "workspace": "/absolute/project/candidates/tess",
  "expected_run_id": "0123456789abcdef0123456789abcdef"
}
```

TaskChoice may optionally declare `task_revision: TaskBinding`. None/absence is
omitted, preserving legacy configuration serialization. Versioned choices project
to the shared authoring task-reference target policy; explicit review uses that
configured native identity without creating a registry or guessing a version.
The existing review HTTP route accepts the typed task_references proposal;
ordinary selections do not trigger composition. The browser provides explicit
selection, Update, findings acknowledgement and current-snapshot adoption through
the [task-version controls](#workflow-builder-task-versions). Python and HTTP use the same
[authoring contract](../workflow_authoring/authoring-contract.md#explicit-task-reference-inspectionreview).
Reusable preparation independently enforces captured native pins.

## Python policy and request binding

`CandidateConsole(config)` exposes `choices()`, `prepare(PrepareSelection)`,
`review(PreparedSelection)`, `launch(LaunchSelection)`, `status(UUID)`, `tokens(UUID)` and
`log(LogReadRequest)`. Methods return typed curated views/native handles and log
chunks, independent of FastAPI. PrepareSelection contains operation_id, task_id,
run_name and three optional advice strings (maximum 32768 characters each).
PreparedSelection identifies prepare_operation_id. LaunchSelection additionally
requires candidate_operation_id and expected_prepared_digest (raw candidate file
SHA256). Native model validators remain the request validation authority.

The shared `preparation_request` builder reconstructs the complete native request
from each configured choice, saved editable values and deterministic UUID paths.
Review/launch require exactly one full equality match before credential access or
submission. Changed/removed/ambiguous configuration does not migrate a preparation.
Code-created preparations obey the same launch policy; status/log/token reads do not
require a matching TaskChoice. The public prepared accessor verifies the complete
native artifact/request association without writes or empty-workspace admission.
Launch compares the reviewed digest and submits the accessor's typed native
request. This freshness check is not execution readiness or complete dependency
immutability. Repeated UUID/request submission retains native idempotency. If
current files changed, inspect the known operation ID rather than creating an
automatic new launch.

Choices expose configured manifest, data root, LLM profile and preparation/candidate
output parents without reading credentials or composing tasks. Prepare selects
separate UUID children; browser paths are observations, not editable run inputs.

Both prepared and edited native review APIs add `credential_readiness` after
verified configured/prepared association (edited review also verifies saved source
and bindings). This ephemeral projection reuses worker `credential_requirements`
and the strict selected private JSON reader. It returns required/omitted provider
names, unresolved route node names, present/missing required or declared names,
`file_status` (`not_needed`, `not_selected`, `readable`, `missing` for a configured
file that does not exist, `unavailable` for one that exists but cannot be read or
parsed), a `ready`
boolean and bounded repair instructions. No file is read when there are no names
to check. Missing/empty extra declared names also block readiness. Invalid or
removed files after startup remain reviewable with `unavailable`/`missing` status; startup
`check` still validates configured credential file shape (JSON or dotenv) and
permissions.

Readiness is absent from native requests, records and review envelope digests.
No values, lengths, hashes, profile payloads or arbitrary private-file errors are
serialized. No environment/dotenv fallback or provider authentication occurs.
Prepared UI renders name-only readiness and disables Launch for known blockers;
Refresh readiness rereads review, without launching. Edited review exposes the
same additive API field for its future launch UI; that UI is not delivered here.
Launch checks identity before reading private credentials afresh. Monitoring and
initial choices do not read credential files; backend admission remains authoritative.

Review exposes stage names, safe route provider/model names, advice, selected task/
data/workspace paths and resource/time policy, never raw bridge_arguments/profile.
Status preserves observed_at, native state, process observation, finishing,
receipt availability, native status/ID and validation_passed; it does not serialize
raw native receipts, arbitrary exception strings, storage paths or scores.

## HTTP boundary

| Method/path | Input/output |
| --- | --- |
| GET /api/choices | `ChoicesView` `{operations_store_id, tasks: ChoiceView[]}`; `operations_store_id` is 32 lowercase hex, a domain-separated SHA-256 prefix of the admitted `OperationStoreConfig` JSON (never a path); browsers key retained operation intents by it and the project id |
| POST /api/preparations | PrepareSelection → OperationHandle, 202 |
| GET /api/preparations/{UUID}/review | PreparedReview |
| POST /api/candidates | LaunchSelection → OperationHandle, 202 |
| GET /api/operations | `limit=1..200` (default 50) → `OperationListView`, read-only; see "Operation list" |
| GET /api/operations/{UUID} | StatusView; 404 `unknown_operation` only after the private store root was opened and lists no such operation (`operation_admitted`); any other missing file stays 404 `not_found`, which never proves absence |
| GET /api/operations/{UUID}/tokens | CandidateTokenSnapshot, read-only fixed native projection |
| GET /api/operations/{UUID}/graph-results | GraphResultsView, read-only per-body native tuning report projection |
| GET /api/operations/{UUID}/log | kind=native or operation, offset>=0, max_bytes=1..65536 → LogChunk |
| POST /api/operations/{UUID}/loop-stop | empty `LoopStopSelection` `{}` → `LoopStopAcknowledgement` (`outcome="requested"`), 200 |
| POST /api/operations/{UUID}/loop-pause | empty `LoopPauseSelection` `{}` → `LoopPauseAcknowledgement` (`outcome="requested"`), 200 |
| GET /api/operations/{UUID}/loop-resume-review | `LoopResumeReview` (owner-verified paused segment, digest, bound, names-only `credential_readiness`) |
| POST /api/loop-resumes | `LoopResumeSelection` (`request_id`, `predecessor_operation_id`, `expected_receipt_digest`) → OperationHandle, 202 |

Outer ASGI RequestBoundary checks exact Host (configured bind/browser authorities),
rejects proxy/forwarded headers and requires constant-time bearer authentication
on every API. Mutation requests require the exact browser Origin; GET rejects a
supplied foreign Origin. Missing/null mutation Origin fails. No cookies or CORS.
Authentication precedes body receive/JSON decoding/business validation. Authorized
JSON mutation bodies are buffered to at most 256 KiB using actual received bytes,
not Content-Length. Non-JSON returns415; oversized returns413. Only `/` and the exact static allowlist in `app.py` are unauthenticated; no
filesystem directory mount
or interactive API documentation exists. Other errors use
`{"error":{"code":"...","message":"..."}}`: auth401, Host/Origin403,
missing operation/resource404, invalid fields422, busy/conflict/stale/integrity/
policy/credential errors409, unexpected500. Validation responses do not echo
inputs. Unexpected failures log exception class only and return secured generic500
inside the boundary; arbitrary native/plugin logs are not universally redacted.

Responses carry no-store, nosniff, no-referrer, frame denial and self-only external
script/style/image CSP. Token is memory-only in the browser; IDs may persist. Page uses
textContent, explicit mutation buttons, retained UUID/payload for retries, visible
polling and stale observation on disconnection. Known-ID monitoring is independent
of draft/review. Server termination does not cancel detached native operations;
OS/cgroup/host lifecycle limitations remain those of candidate_operations.

## Presentation preferences

`/theme.css` owns semantic colors shared by console and editor; `/theme.js`
applies the initial theme before styles/body load under the existing self-only
CSP. The native `Color theme` select exposes System (initial default), Light and
Dark. System follows `prefers-color-scheme` changes; explicit selections take
precedence. Only the validated enum is stored in `siderius.console.theme`.
Invalid stored values use System. Storage read/write denial leaves selection
working in page memory. Future loads reuse any readable previously stored enum;
missing, invalid or unreadable preferences fall back to System. A failed write
does not erase an older stored preference.

Theme changes only update the root `data-theme` attribute: no reload, API calls,
new polling timers, draft/source mutation or review invalidation. Existing
operation IDs, graph selection and editor state retain their owners. All shell views
use the same tokens for controls, warnings, disabled states, focus and selected
HTML graph nodes. These console/editor surfaces currently render declarations
as HTML nodes/text connections and reported usage as a table. The theme browser
gate qualifies those surfaces; it makes no claim about other or future renderers.

Theme browser gate: with this checkout's frozen `EDITOR_PYTHON`, existing
`CONSOLE_PLAYWRIGHT_MODULE`, `CONSOLE_BROWSER_EXECUTABLE` and optional
`CONSOLE_SCREENSHOT_DIR`, run `node tests/browser/console_themes.mjs`.
It starts the temporary editor API fixture on an ephemeral loopback port and
intercepts console observations; no native operations or provider calls run.
It checks preference/system/keyboard/storage behavior, retained pending
inspector/source/review and monitoring identity, contrast and desktop/narrow
screenshots in each theme. Screenshot contents are synthetic fixtures.

## Validation

Focused deterministic suites: `tests/unit/tools/candidate_console`, native
preparation/operation suites and `tests/unit/tools/test_workflow_preview.py`.
`SIDERIUS_TEST_WORKSPACE_SANDBOX=1 .venv/bin/python -m pytest
tests/integration/tools/test_candidate_console.py -q` opts into a real local
loopback server, native sandbox and CPU validation with a test-only fake provider;
no paid API/GPU evidence is implied. It verifies admitted candidate survival after
HTTP server exit and fresh known-ID reads.

Browser gate: supply `CONSOLE_PLAYWRIGHT_MODULE` (an installed Playwright module),
`CONSOLE_BROWSER_EXECUTABLE` (matching Chromium), `CONSOLE_TEST_ORIGIN` (free
loopback origin) and optional `CONSOLE_SCREENSHOT_DIR`, then run
`node tests/browser/candidate_console.mjs`. No production browser dependency or
Node build is required. The test serves fixed assets and mocks API responses;
it proves browser interaction, not native execution/security. Browser/process
socket support may require a host execution context. Missing tooling is a missing
gate, not a pass. Screenshots cover desktop/tablet/mobile and a 200% equivalent
CSS viewport; they do not claim browser-chrome zoom automation.


## Reported-token monitor

`CandidateConsole.tokens(UUID)` calls the public `read_operation_tokens` adapter,
which binds admitted request, native nonce and operation integrity before reading
usage. The authenticated GET accepts only operation UUID, no browser workspace
path or task choice. Preparation returns explicit not-applicable; native publication
pending returns unavailable and recovers on later reads. Identity corruption
returns sanitized integrity failure before ledger access. Unknown wrapper process
observation alone does not hide valid token evidence. Token data contains no raw
ledger rows/extras/components, credentials, prompts or receipt paths.

The existing visible-page two-second poll reads tokens independently of status/log
success. Snapshot rows replace the table; failed reads retain only the selected
operation's last table with a stale label. Operation selection clears the previous
table immediately, and the existing monitor epoch fences delayed responses.
Null fields show Unavailable; reported zero remains 0, with independent missing
counts in input/output/total cells. Partial evidence and read/last-valid-usage UTC
are separate labels. Model identities use textContent inside a responsive,
keyboard-focusable scrolling table. The fixed coverage note always remains visible.
No additional poller, persisted snapshot, cursor or billing authority is added.

The native [projection contract](../candidate_worker/candidate-worker-contract.md#reported-token-read-projection)
owns arithmetic, quality, limits and evidence semantics. Focused HTTP tests prove
route reachability, auth/Host/Origin/UUID checks before reader entry, no-store/CSP
and sanitized failures. The browser harness adds null/partial/stale token views,
replacement polling, token-only failure isolation and old-run epoch fencing.

## Verified graph tuning results

`CandidateConsole.graph_results(UUID)` delegates to
`graph_results.read_graph_results`. It calls `read_operation` (which already runs
`verify_candidate_records`, including `verify_graph_trace`/`verify_loop`) and
`lookup_operation_request`; it adds no admission, scoring, ranking or reduction
policy. Operation status semantics are unchanged; `StatusView.loop` is described
under [Authored loop Stop and state](#authored-loop-stop-and-state).

- `available=false` unless the snapshot state is `completed`, its receipt is a
  `CandidateRunReceipt` with `graph_trace` or `loop_trace`, and the admitted
  submission is a `CandidateOperation`, or a `CandidateLoopResumeOperation` whose
  root candidate comes from `candidate_operations.loop_root_operation` (immutable
  predecessor records only). A paused or resumed segment therefore lists every body
  that `verify_loop(root request, root launch.json, segment receipt)` accepts up to
  that segment's own receipt. Fixed (non-graph) candidates, active,
  failed or integrity-unknown operations return `available=false` with no bodies.
- Bodies: a standalone graph yields its one receipt. A loop yields exactly the body
  receipts returned by `verify_loop(request, launch.json receipt, receipt)`, in
  verified iteration order (`iteration` = 1-based position). A loop with no
  verified completed-body index (`attempted_iterations == 0`) returns `available=false`
  with no bodies. Body membership is never inferred from directory names.
- Per body, the tuning node is the declared `execution_families(...).tuning`
  node in that body's `graph_trace`. Only `state == "succeeded"` reads a record:
  its `record_sha256` is re-checked with `record_digest`, then the file is validated
  as JSON and against the `HyperparamTuningOutput` schema. Any other state returns
  `result=null` (no score, even if a record file exists).
- `GraphRunSummary` is the path-free subset of `RunView`: run name, model type,
  status, termination reason, times, completed rounds, total attempts, `metric`,
  `metric_source`, `ranking_refusal`, declared secondary metric identities, the
  tuner's own `RunHeadline` and `status_counts`. `source_path`, provenance,
  storage/record paths, raw `all_records`/attempts and failure detail are absent.
- Failures: a missing tuning node, missing record identity, changed digest,
  unreadable/invalid/schema-invalid record, or a refused loop re-verification raises
  `OperationFailure("integrity", ...)` → HTTP 409 with the generic sanitized
  message; an unknown operation is 404.

Monitor: `graph-results-monitor.js` owns `window.renderGraphResults` and the
`#graph-results-observation` section. `app.js` requests the route once per
selected operation inside the existing poll, only for `kind == "candidate"` and
`state == "completed"`; the existing monitor epoch fences replies and selection
clears the section. 404/409 are final for that selection; other failures retry on
the next existing poll. Each body is its own section (`Iteration N` for several
bodies) whose stage label comes from `editorCapabilityPresentation.label("tuning")`
(`Train & tune`). No cross-body score or ordering is computed or displayed.
Non-integer numbers are display-rounded by `number-format.js` (up to four
decimals; four significant digits for magnitudes below 1e-3 or from 1e9); the
exact reported value stays in the cell's tooltip. Stop-condition values in the
loop state are rounded the same way, with exact values in its tooltip. Stored and
transported values are unchanged.

Witnesses: `test_console_graph_results_reuse_native_run_report_without_paths`
(native graph record vs `project_run`, no path, failed stage has no score, changed
record refused), `test_two_native_bodies_preserve_advice_and_verify_feedback`
(two loop bodies in verified order, refused body → integrity) and
`tests/browser/graph_results_monitor.mjs` (synthetic GET-only two-body render).
Provider and tuner effects are offline doubles; these establish projection, not
scientific training. No public paired prepared/completed example exists yet.

## Authored loop Stop and state

`StatusView.loop` is present only for an authored-loop `candidate` or
`candidate_loop_resume` segment. `final_iteration` comes from the root candidate's
declaration (`candidate_operations.loop_root_operation`, which follows immutable
`predecessor_operation_id` records, never directories) and `attempted_iterations`
only from this segment's native receipt `loop_trace` (`null` while no receipt
exists; counts are cumulative over the run). `stop_reason` is the receipt's
verified `loop_trace.stop_reason`, present only when a declared stop condition
completed the loop early; Monitor renders it in plain words ("Research loop
stopped early after body 3 of up to 5: accuracy reached 0.9 (threshold 0.85,
higher is better; best at body 3)", or "… no improvement for 2 bodies …") from
the existing status poll, with recorded values unrounded. The receipt's body
numbers (`attempted_iterations`, `stop_reason.iteration` and its incumbent
iterations) are whole-run indices, so a resumed segment's line says "Body numbers
count the whole run, including earlier segments." The console never
infers per-body progress from an active process. `stop_requested` and
`pause_requested` (status only; `false` in the operation list) are read by
`candidate_operations.loop_control_requests` from the worker's own durable markers
with the worker's scoping: Stop is run-wide (`candidate_run/stop.json`), Pause belongs
to this operation's segment only (root `candidate_run/pause.json` or
`continuations/<segment>/pause.json`). They report recorded requests, never their
effect; the receipt still decides whether a Stop or Pause took effect. Monitor renders
the Stop/Pause controls from these fields, so a reload or another tab shows a pending
Stop and hides Pause once a Stop is recorded. Fixed and non-candidate
operations omit the field. `StatusView.successor_operation_id` forwards the
operations readback for a segment that a Resume has continued; the segment keeps
its own receipt.

`CandidateConsole.request_loop_stop(UUID)` delegates once to
`candidate_operations.request_loop_stop`, which owns admission, identity checks,
idempotency and the write-once marker. HTTP POST `/api/operations/{UUID}/loop-stop`
passes the ordinary mutation boundary (bearer token, exact Origin, JSON content
type, 256 KiB limit) and accepts only the empty JSON object. Success returns
`{"operation_id": UUID, "outcome": "requested"}`; it means the request was
recorded, never that the loop stopped. The active body completes; the final
iteration or a native failure may still end the loop first. Refusals: unknown
operation 404; `kind` (not an authored candidate loop), `not_ready` (worker has
not claimed its workspace) and `not_running` (terminal or not confirmed running)
409 with route-local fixed messages; `integrity` and others 409 with the generic
message. Native detail and paths are never echoed. A repeated POST after the
Stop marker exists replays the recorded request and returns 200 `requested`
even when the loop has since become terminal (the backend replays the marker
before its running check); a 200 is therefore an idempotent acknowledgement,
never evidence that the loop is still running.

Monitor: `loop-control.js` owns `window.renderLoopControl` and
`#loop-control`, rendered from each existing status poll (no extra polling).
**Stop at next boundary** is shown only for a status with `loop` (root or resumed
segment), state `active` and no receipt. A click disables the button for the pending request, so
one click sequence issues one POST; after acknowledgement the button is hidden and
the state reads "Stop requested … Not yet stopped." until a receipt arrives. A
receipt `stopped` reads "stopped at a completed body boundary after N of M
bodies"; `completed` reads "finished after N of M bodies" (and notes that a
requested Stop did not take effect); `paused` is described under Pause and Resume;
other statuses read "ended (status)". The
acknowledgement is memory-only for the selected operation: a reload or another
selection forgets it, because no marker read exists and the receipt is the
authority. Witnesses: `tests/unit/tools/candidate_console/test_loop_stop.py` and
`tests/browser/loop_controls.mjs` (stubbed API). The worker Stop semantics are
witnessed by `candidate_worker/test_finite_loop.py`.

### Pause and Resume

`CandidateConsole.request_loop_pause(UUID)` delegates once to
`candidate_operations.request_loop_pause` (same boundary and body rules as Stop).
Success is `{"operation_id": UUID, "outcome": "requested"}`: requested, never
paused. Pause applies to the selected segment only; a resumed segment is paused by
its own UUID. Refusals: unknown 404; `kind`, `not_ready`, `not_running` 409 with
route-local fixed messages; others the generic message.

`CandidateConsole.review_loop_resume(UUID)` calls `review_loop_resume` and returns
`LoopResumeReview`: the predecessor UUID, the owner's `receipt_digest` as
`expected_receipt_digest`, completed bodies, the root bound and name-only
`credential_readiness` for the root request (no values). `resume_loop` submits
`CandidateLoopResumeOperation` through `submit_operation`. If the request UUID is
already admitted it replays with an empty environment before any root or credential
read, so a retry after an unconfirmed outcome returns the same operation. Otherwise
the root's `environment_names` are read from the configured `credential_file` with
the same `credentials` helper as Launch. Refusals on both routes: `loop_resume`
(not an exited, cleanly paused segment, already continued, terminal, or a stale
digest), `kind`, `not_ready` and `runtime` 409 with route-local fixed messages;
`credentials` 409 carrying missing names only; `busy`/`conflict` use the global
messages. Unknown predecessor 404.

Monitor shows **Pause at next boundary** beside Stop for an active loop
segment with no receipt; after acknowledgement it reads "Pause requested … Not yet
paused." A `paused` receipt reads "paused at a completed body boundary after N of M
bodies" and is resumable, never "ended". Without a successor it offers **Review
resume** (one GET on click, never polled), then **Resume loop**, disabled unless
credentials are ready. The client generates one request UUID per reviewed digest
and retains it in `localStorage` (`siderius.loop-resume.v1:<predecessor>`) before
the POST; a retry reuses it, and the record is released once status shows the
successor. A 409 clears the review. On success the monitor selects the resumed
segment, which reads "Resumed segment." and shows Stop and Pause while active and
its per-body results once completed. A continued predecessor shows "Continued by
<UUID>" (a Slow-control link) and no Resume. Witnesses:
`tests/unit/tools/candidate_console/test_loop_pause_resume.py`, the console
projections in `candidate_worker/test_loop_resume.py` (real two-segment store), and
`tests/browser/loop_controls.mjs` (stubbed API).

## Recorded candidate examples

`ConsoleConfig.recorded_examples` defaults to empty. The authenticated
`GET /api/recorded-examples` lists only configured entries; the detail GET takes
an allowlist ID, never a browser-supplied filesystem path. Monitor presents
the captured three-stage proposal/implementation/validation result, labelled with
the editor's paper capability names, and reads
reported provider usage through the existing candidate-token owner and shared
token presenter. The panel labels this **candidate validation only**. It is not
a `StatusView`, operation, training result, scientific score or billing record,
and it offers no prepare, launch, retry, review or import action. A missing
captured source snapshot is reported as unavailable; source export and editing
remain separate work. The browser witness checks GET-only requests, forbids
credential and submission calls, and verifies the configured record files remain
unchanged.


## Optional ordinary-file Editor

`ConsoleConfig.editor_projects` defaults to an empty tuple. Each typed `Project`
selects `project_id`, explicit absolute `project_root`, `source_file` and
`recovery_directory`. Configuration check admits those resources inertly and
refuses recovery/output-root overlap. No source is required when selection is
absent. `CandidateConsole` retains only native operation policy; `editor.py`
constructs separate `WorkflowAuthoring` services and routes.

`/editor.html`, `/editor.js`, `/editor.css` and the editor modules named below are static assets (`app.py` serves an exact name map). The editor shares
the persistent shell and memory-only session with the operation monitor; its
source/review policy remains owned by `editor.js`. `GET /api/editor/projects`
returns configured IDs. `GET /api/editor/{project_id}` returns `SourceView`.
`POST /api/editor/{project_id}/review` validates `ReviewRequest`; `POST
/api/editor/{project_id}/save` validates `SaveRequest`. GET
`/api/editor/{project_id}/versions` returns `VersionList` and GET
`/versions/{index}?sha256=` returns read-only `VersionDetail` (see named versions
in the authoring contract); `editor-versions.js` renders the Save name field and
Version history panel and owns no record policy. History is a beginner surface
(`⋯` › Version history, red-team A-3): rows show name, time and Current; SHA-256,
the record path and the whole saved Python are advanced detail. **View** opens a row;
**Restore this version as a draft** (`#editor-history-restore`, not offered for the
current row or a row without kept bytes) hands its bytes to
`workflowEditor.restoreVersion`, an ordinary `source` review folded into the draft as
one undoable step: nothing is written until **Save version**, and Undo brings back the
replaced edits. It refuses, with a status sentence, while an invalid field draft,
typed Python text or a conflict is pending. A file without a console-saved row is
"Current file (not saved in the console yet)", never a saved version. The name field
refuses, as typed, invisible characters (the categories `NewVersionName` refuses) and
a name already in the loaded history (`#editor-version-problem`, Save disabled); no
other naming rule. Save error `version_record` means nothing was written (the
reviewed proposal is retained); the distinct `version_record_not_updated` means the
source was saved but its record was not, so `editor.js` adopts the returned saved
`current` view. `GET /api/editor/node-catalog`
and `POST /api/editor/{project_id}/nodes-draft` serve the node palette, and
`GET /api/editor/external-inputs` serves the inspector's input creation (projects
named `node-catalog` or `external-inputs`, like `projects`, are shadowed by the
fixed routes; the older single-node `node-draft` route remains for API clients). The existing console
Bearer token, origin, host and 256 KiB wire-body admission apply to every API
route. Browser requests select project IDs and never filesystem destinations.
The [authoring contract](../workflow_authoring/authoring-contract.md) owns source
limits, exact-byte review/save, mode preservation, recovery and race boundaries.
Domain conflicts return bounded current source/diagnostics and, on a stale
Review, the rendered pending proposal/diff. Unsupported-source and parser
failures do not execute selected Python. Unexpected filesystem failures report
an unavailable resource without forwarding exception text: on a read, "The
workflow file or its project folder is unavailable on disk"; on Save, "Not saved:
the project folder or its recovery copies could not be written". Typed open
refusals (`not_found`, `not_readable`, `limit`) and the Save refusal `read_only`
name the configured path (authoring contract).

Editor task/external fields and existing request/protocol argument choices use
the native declaration document and a typed projection of the existing catalog.
No JavaScript contract inventory or alternate graph schema is authoritative.
The circuit renders existing authored request/argument sockets and result outputs.
`editor-circuit.js` owns presentation/ephemeral gestures; `editor-circuit-geometry.js`
contains prototype-derived obstacle routing and display-only fallback layout.
Neither owns a graph, catalog, schema, request or execution engine. Type-compatible
rebinding uses exact existing server BindingChoices. Circuit and inspector call
one editor.js mutation; dragging writes positions through that same draft owner.
Bindings/profile/options are not inferred from card order or geometry. Request
protocols display inside their actual consumer, not as extra nodes: a protocol
node's card carries a `.circuit-adapter` chip ("Mapping: <protocol id>", coloured by
the protocol's output contract) below its output row, where upward port tooltips
(which take no pointer events) cannot cover it, that expands, per card and remembered across
re-renders of the same graph, into one row per inventory argument
(`<source> → <argument>` with the socket contract) and the native owner function
that maps them into `protocol_mapping.output_contract`. External-request nodes have
no chip.

Port legibility is presentation keyed on the server-sent contract id
(`editor-contract-presentation.js`, styles in `editor-contract-presentation.css`).
Names, descriptions and kinds are not owned by the browser: every projected
contract object carries `name`, `description` and `kind` from the single server
owner ([contract schema names](../../workflows/definition/contract-names.md)),
and the module learns them from those objects. Its table gives each catalog
contract only a colour token
(`--contract-<colour>`, defined for both themes) and a socket shape (`circle` for
`<capability>.input`, `square` for `<capability>.output`, `diamond` for
`optional.*`, `capsule` for other contracts); a unit census binds the table to
`CONTRACTS` and requires distinct (colour, shape) pairs. An id missing
from the table (a newer server catalog) gets a stable hash-derived token, and an
id without a server name shows id-derived words. A name names the schema only;
each canvas socket carries a direction arrow (before an input's label, after an
output's; `data-contract-direction` `receives`/`sends`, accessible name and
tooltip prefixed "Receives <name>." / "Sends <name>."), and the legend note explains
both arrows; each legend row's tooltip is the type's server description (rows stay one line). Port
pills show the readable name (the id stays in the tooltip), wires take the colour of
the result they carry, required inputs and outputs have filled sockets and optional
inputs hollow ones, and a closed "Connector types (N)" legend (two-column popover) lists the contracts present
in the opened graph. The table never decides compatibility. Connection preview
reads only the server's `port_inventory` choices: hovering an output highlights
offered inputs and dims the rest without selecting; pressing an output and releasing
over an input binds exactly as output-then-input clicks do. A refused or dimmed
input states (spec K10) `Can't connect: <source module> sends <name>; this input
receives <name>.`, or that the source module is not offered for this input although
both contracts match; a refused drop also shows that sentence anchored under the
input (`.circuit-anchor-note`, removed by the next gesture or render).
External source chips remain inspector bindings. Omitted optional ports and argument
creation/deletion are not graphical controls in this slice.

The node palette (`editor-palette.js`, `editor-palette.css`; presentation only,
`editor.js` owns the draft) is the docked rail of the editor workspace
(`.editor-workspace` in `editor.css`: `--rail-width`, own scroll, sized with the
`theme.css` layout tokens) so a drag source and the canvas share the screen; under
900px it collapses to a drawer opened
by its "Modules" toggle. Entries are focusable `div[role=button]` (click,
Enter or Space; `aria-disabled` while inactive) carrying a prefixed `text/plain`
drag payload. It lists
`GET /api/editor/node-catalog` entries (fetched once per connection, only while the
Workflow view is shown; other pages never request it) as a compact, aligned stack
of one uniform-height collapsed `details.palette-category` row per capability (icon,
display name from `editorCapabilityPresentation.label` on one line with
ellipsis and a full-title tooltip, a dot marker with accessible text and tooltip for
"Start here" on `guide.chain[0]` / "Optional context" on `guide.context`; no
step-number badge, the stack is already in stage order) in `guide` stage order, with a text search (matching rows open). Above the
stack a one-sentence start guide renders `guide.chain` (emphasised while the canvas
has no card) with a "Using this list" disclosure naming `guide.context` (the header
Help opens the tour; there is no second, look-alike help entry). Expanding a row (accordion, open state kept across re-renders) shows the
server description, the sent type, connects-from/to and one addable `.palette-entry`
per route with contract chips: "→ <name>" for each received (required) type and
"<name> →" for the sent type (`data-direction` receives/sends, accessible text
"receives"/"sends"; optional ones counted). Type names, colour and shape come from
`editor-contract-presentation.js` `describe()`, which learns the server contract `name`
(owner `workflows/definition/contract_names.py`) from the catalog contract objects. Hover or keyboard focus on a route shows
one shared `#palette-popover` (`role=tooltip`, `aria-describedby`; Escape, blur or
leaving dismisses it): description, request route, every received argument with
type, required/optional and origin (`produced_by` capabilities or external input),
the sent type and connects-from/to. While shown, canvas ports get
`palette-compatible` when an output carries a contract the route reads from another
capability or an input's socket contract equals the route's output contract
(presentation only; binding still uses server `port_inventory` choices). The
presentation lives in `editor-palette-guidance.js`. The palette adds one by click (placed right of the existing cards) or by dragging an entry
onto the canvas (dropped at that world position). It proposes an unused instance
id (`<capability>`, `<capability>2`, ...). Pending nodes are the unified draft's
`nodes` list and new external inputs its `externals` list (`editor-node-drafts.js`,
`window.editorNodeDrafts`, holds their projection and list edits; `editorDraft.proposal`
turns them into one `node_drafts` proposal on `anchor.source`, see the authoring
contract). Any number of nodes may be pending beside moves, wiring, inspector,
reference and loop edits; everything is part of the dirty flag, undo/redo and Discard.
Every card, pending or saved, can be moved at any time. Moving only pending cards
records only their positions, so the review stays a byte-preserving insertion. The
canvas and Selection draw the edited document plus pending nodes. Ports come from
`POST …/nodes-draft`, which covers the whole projected graph; its choices include
pending results and new inputs. `editor.js` caches views by `editorNodeDrafts.key`
(layout excluded, so moves never re-inspect) and reuses the last view while checking.
Unbound required inputs show red (P2) and are wired with the ordinary
canvas/inspector gestures, saved -> pending and pending -> pending included. While
anything is pending, Review is disabled until the current view is `complete`. The
binding-only `…/draft` inspection is then not used, because `nodes-draft` also
applies the binding patches. Removing a pending node ("Cancel new node" for the
newest, Delete, context menu or Selection) is an undoable draft operation and sends
no request. Sockets that read it are disconnected (pending) or return to their saved
source (patches); the status line names them. Removing a *saved* node still needs a
draft with no structured edits over its anchor. A successful `node_drafts` or
`remove_node` review becomes the draft's new anchor (one undo step, like a reviewed
Source edit).

Inspector input creation (`editor-external-inputs.js`, `editor-external-inputs.css`).
Under each unbound socket whose contract `GET /api/editor/external-inputs` lists,
Selection shows one line: the contract name (`editorContractPresentation.describe`,
the `contract_names.py` owner), the server `summary`, and whether
existing inputs of that contract are offered in the select above. A collapsed
"Create external input…" form asks for an input id (suggested `<node>_<argument>`,
de-duplicated). In a version 1 document it also asks for the project-relative file
path; the path is never prefilled, only an `e.g. inputs/<id>.json` placeholder. A
reusable (schema 2) document never offers a file (red-team SEC-6: reusable preparation
accepts only managed inputs): a `managed` contract creates a `managed_candidate`
binding with no path, and a contract without a managed form shows the form disabled
with that reason. "Create and connect" validates the id (identifier, unused) and, for
a file input, a non-empty path. It then adds the binding to the draft's
`externals` and connects the socket as one undoable operation ("Create input …").
The server validates the result.
Deletion is offered by Delete/Backspace on a focused module heading (a mouse click
focuses the clicked heading after the select re-render, so click-then-Delete works),
its context menu ("Delete module") and the trash icon in the Selection header
(`aria-label` `Delete <id>`). It always succeeds in the draft with no confirmation
(`removed` in the node-drafts proposal); readers become "not connected" problems and
Undo restores everything. Problems name only modules that remain: the server reports
removal, remaining-reader and pending-module problems together, an emptied canvas has
the single problem `workflow_empty` ("add at least one module"), and
`loop_feedback_missing` stays while either loop endpoint is deleted, even after new
modules are added. The browser also drops located problems whose module is no longer
displayed and re-diagnoses from a cached inspection on every edit; the Research loop
section shows `#editor-loop-broken` (only Remove research loop) instead of
stop-condition edits while the loop points at a deleted module.
Required and bound inputs always render as card rows; optional unbound inputs fold
into one `.circuit-optional` disclosure per card ("N optional inputs"), expandable
and remembered across re-renders of the same graph. While an output is pending,
the summary is highlighted when a folded input is type-compatible.

Canvas view state (zoom, scroll, expanded optional rows) is owned by
`editor-circuit.js`, keyed by project and node IDs, and never reaches a document:
viewing sends no request and cannot change saved bytes. The canvas is a CSS
`transform: scale()` of the world, with positions kept in document pixels
(drags divide screen deltas by the zoom). On opening a graph it fits once
(`editorCircuitGeometry.fitScale`: never above 100 %, never below 40 %, then the
canvas scrolls); the toolbar offers Fit to view, zoom out/in, Actual size, Check
the loop and Tidy up (the one layout tool; the former display-only Arrange view was
removed because a drag in it saved the arranged layout, red-team A-1). The canvas
grows with its zoomed content up to `clamp(420px, 100vh - 200px, 860px)`, shows edge
shadows toward unseen content, and a note states how many modules are partly outside
the view. Overlapping saved cards (`geometry.overlaps`) and unrouteable wires are
reported with Tidy up (undoable) as the way out.

The workflow-level Research loop panel (`editor-loop-controls.js`, view only;
`editor.js` owns the draft) shows "No research loop declared" with an Add action
enabled only when the server returned `loop_template`, or the declared loop as one
fieldset per facet: Iteration limit (`final_iteration`, whole number ≥ 1; invalid
or empty values stay local and block Review) and Feedback (paper capability labels
from `editorCapabilityPresentation.label`, read-only endpoints). Remove deletes the
loop. Loop-only edits review as `LoopProposal` on the draft's anchor source; with
other draft edits pending, the document or draft proposal carries them. A third
fieldset, Stop conditions, adds/removes at most one `metric_threshold` (metric id
text plus threshold; the editor does not know the task metric) and one
`no_improvement` (completed bodies); `judge` is never offered. All stop-condition
UI logic lives in `editor-loop-controls.js`, mutating the draft loop through one
`edit` action from `editor.js`. Empty, padded, non-finite or non-integer values
stay local in the loop draft state (`loopDrafts`, separate from training drafts)
and block Review and circuit edits exactly as an invalid limit does. Cross-field
rules (one per kind, `completed_bodies < final_iteration`) are the declaration's:
a refused loop review reads "Review refused the research loop: …" with the
diagnostic `field_path`. Loop edits preserve bytes only for an already-canonical
source; Review re-renders the whole declaration, so hand-formatted or commented
sources are rewritten (visible in the diff). The panel
does not draw a back-edge or annotate cards, and it shares the source-dirty,
conflict and saving fences of the unified draft. Capture review (`ReusableCaptureReview.loop`)
reports the executed request's authored loop, refusing a request loop that differs
from the captured declaration, and the launch summary states "up to N iterations"
or "none (one workflow body)", followed by "stops early when …" for each declared
stop condition.

The Selection inspector groups one node's parameters (`editor-node-parameters.js`,
view only; `editor.js` owns every mutation): **Inputs** (one binding select per
socket, required/optional and bound state in its label; a required unbound one is
marked `.field-problem`), **Training settings** on a tuning node (a
`#editor-training-settings` disclosure, collapsed by default (an opened one stays
open across re-renders) with summary `Training settings · N of M changed`, listing every
`TrainingInspector` control with its mode select (`Default` / `Set value` / `None`),
value, a per-field reset icon (`[data-training-reset]`, shown and enabled only when the
field is changed) that removes the authored key, a `Default` / `Modified` / `Changed, not
saved` badge against the native default and the loaded source, an invalid-number
message under the field (`.field-error`), and inline help from `TrainingControl.help`;
the schema default / native preview, epoch-ceiling prose, output restriction and
parameter-rules JSON are advanced detail), **Loop and stop settings**
on a feedback endpoint (a summary and a button to the workflow-level Research loop
panel) and **Model hyperparameters** on a tuning node (read-only: they are owned
by the task manifest, shown as `definition.task.manifest` and any task binding;
no control edits them). A card whose server inventory has a required unbound input
gets `.has-required-unbound` and a small `.circuit-problem-badge` count; the soft red
ring is on the unconnected socket itself.
`#editor-problems` (`editor-problems.js`, beside Review) lists "N problems" from
server diagnostics only: draft `problems` (`DraftProblem`) and source diagnostics
(`SourceDiagnostic`). It is hidden when empty. A located item selects its node and
focuses the inspector select for `field` (and marks the canvas input
`.problem-focus`); an unlocated item opens Advanced source at its line. The
list never enables Review: Review remains disabled for an incomplete draft.
Witness: `tests/browser/required_defaults.mjs`.

Unified draft (`editor-draft.js`, `window.editorDraft`; `editor.js` delegates).
Wiring, disconnection, layout moves, inspector, training, research-loop edits and
pending palette nodes and new external inputs are operations on one draft state
`{document, bindings, anchor, nodes, externals, training, loopTemplate}`: `document` is the edited authored document, `bindings` are
`BindingPatch` values relative to `anchor.inventory`, and `anchor` is the last
server projection the draft starts from (`{source, document, inventory}` of the
loaded source, or of a reviewed Source/task-reference update). There is no edit
mode: any mix accumulates, with one dirty flag (`workflowEditor.state.dirty`,
true while the draft identity `{document, bindings, anchor.source, nodes, externals}` differs from
the loaded state, or while Source text is dirty). Review selects the existing
typed proposal from the draft: pending nodes or new inputs → `NodeDraftsProposal`
on `anchor.source`, which carries `document` only when the saved content was edited
and the binding patches (see the node palette below); patches present → `DraftProposal` whose
`base_document` is the edited document (layout and inspector edits travel with
the patches); otherwise document changes outside the loop → `DocumentProposal`;
loop-only changes → `LoopProposal` on `anchor.source`; no change →
`SourceProposal(anchor.source)`. Dirty Source text reviews as `SourceProposal`;
its reviewed projection becomes the new anchor as one history step. Binding
inspection (`POST …/draft`, read-only) belongs to the current patch set: layout
or inspector edits keep it, any patch change (including undo/redo) re-inspects,
and Review stays disabled until the current patch set inspects `complete`. A
no-op input event is not an edit. The server API is unchanged.
Training-settings actions from `editor-node-parameters.js` (value, mode, per-field
Reset) are draft operations too: typing in one field coalesces, each Reset is its
own undo step, and undo/redo re-render the badges from the restored document.
History: every operation records one undo step (consecutive typing in one field
coalesces, limit 200). **Undo**/**Redo** buttons and Ctrl/Cmd+Z,
Ctrl/Cmd+Shift+Z, Ctrl/Cmd+Y (outside text controls, Workflow view only, and never
while a `dialog[open]` exists or a `[role=dialog]` / `[popover]` element holds focus,
red-team A-4) restore
earlier states and invalidate any review. **Revert to saved** (`#editor-discard-draft`,
visible label beside its icon, red-team A-5) restores the loaded
state without reading disk and is itself undoable, including dirty Source text:
the discard step carries the typed text (`sourceText`) and Undo restores it as
dirty Source text (invalid training/loop field text is not kept). While typed Source
text (dirty, or checked from typed text) is pending and advanced tools are off,
`#editor-hidden-source` says "You have unsaved Python edits from advanced mode" with
Show (turns advanced tools on and focuses the source) and Revert to saved, and the Save step
says it writes the typed Python text (red-team A-2). **Reload from
disk** (`#editor-refresh`, advanced; and `#editor-discard` on the conflict card) is the
only action that re-reads the file; the toolbar one asks first when dirty. Undo/Redo are disabled while Source
text is dirty or an invalid training/loop field draft is pending (Ctrl/Cmd+Z
then reports why and keeps the typed text); Undo/Redo/Discard are disabled
during Save and while a conflict is shown (the conflict panel's own
**Reload from disk** / **Reapply my changes onto latest** apply). Rebase stays disabled while binding patches are pending;
it makes the current disk version Discard's target and restarts history there.
Structured edits are re-applied onto the disk projection by a three-way merge
(`editorDraft.reapply`, ancestor = the previous base document; arrays merge by
`id`/`node`/`name`; where both sides changed one value the draft's value wins
and the status names the paths), so later proposals keep the disk change.
Pending Source text (dirty, or reviewed into the anchor) is a whole-file
proposal and is kept unchanged; the status states that it does not include the
disk change. A dirty draft prefixes the
page title with `* `, shows an "Unsaved changes" badge in the Workflow heading and
arms the `beforeunload` guard. Save still writes exactly the reviewed bytes and
resets history to the saved state.

Socket/drag gestures send no review or save requests. Source editing, disconnection, conflict,
saving and invalid training/loop drafts gate mutations (invalid drafts do not block
capability selection, which is navigation); stale rendered projections
cannot mutate a replacement document. Required whole-declaration checks remain
Review/Save, with execution-profile/alias admission owned by separate native
preparation. Type-compatible highlights do not claim runtime compatibility. Existing
unrouteable/overlapping layouts retain every binding in the textual connection list.
Stored positions remain exact. Nodes without one get a display-only fallback placed
right of every stored card (card size is measured from the rendered cards), so a
partial code-authored set never overlaps. A pointer drag and Alt + arrows call the
same move: it records every displayed position, the moved one updated, so the next
open shows the same layout; a save without a move keeps positions unchanged.
Keyboard buttons share pointer actions; Escape/right-click cancels a pending wire.
Card headings, palette, loop, run and result views use one sentence-case display
name per capability (`Interpret results`, `Literature review`, `Propose model`,
`Implement`, `Validate`, `Train & tune`; the paper figure's stages in plain words)
from `editor-capability-presentation.js`, their single owner;
a unit census binds that table to the catalog. Shared semantic theme tokens own colors.

Source/form/base changes invalidate Review. Unreviewed inspector edits disable
the source textarea until Review synchronizes the rendered proposal, preventing
a stale source buffer from silently replacing form changes. Source edits disable
the stale inspector until successful Review projects the source. Explicit project
selection clears prior source, graph, conflict and actionable controls before
loading; reconnect retains pending drafts and reviewed bytes. Failed loads cannot
adopt an old project conflict.
Async replies are fenced by selected project and local edit generation; Save sends exact reviewed bytes/hash.
Conflict handling preserves the pending proposal and requires explicit discard
or new-base selection followed by review. The conflict card (red-team S-5) states
in one sentence that the workflow was saved from another tab or changed on disk
(with the time noticed) and that unsaved changes are kept; **What changed on disk**
is a unified line diff (`editor-save-outcome.js` `lineDiff`, three context lines)
from the version the page opened to the file now; **Your unsaved changes** lists
binding/node drafts or a line diff of the proposal; the whole current file is
advanced detail.

Save outcomes (`editor-save-outcome.js`, red-team S-2..S-4) are one plain
sentence each. A 4xx refusal wrote nothing: "Not saved: …" with the refusal's own
reason (busy, read-only file, version name, filesystem, task sources …), and the
checked proposal and open Save step stay ready for another try (a `proposal` hash
refusal drops the check). A 5xx, an unreadable reply or no reply leaves the outcome
unknown: the editor re-reads the file and reports "Saved (confirmed from disk)" when
it holds the checked bytes, "Not saved: … The file on disk is unchanged" when it
holds the base, and the conflict card otherwise. A save whose follow-up reload
fails reports "Saved as "<name>". Reloading the file afterwards failed: …" and
adopts the checked review projection as the saved state, so the next save is no
false conflict; a save conflict whose disk bytes equal the checked bytes is adopted
as already saved. When the review's `removed_comments` is non-empty, the Save step
(`#editor-save-comments`, beginner view) says "Saving rewrites the file: N comment(s)
will be removed (…)", also after **Reapply my changes onto latest** (red-team S-1).
A server check of a binding or node draft that fails (e.g. a non-JSON 5xx) puts
that draft state in `check failed` with **Check again** (`#editor-check-again`)
instead of "checking" forever; the failed state is not re-sent automatically, and
any edit (a new draft key) is checked as usual (red-team E-5). Status sentences are
plain: "Opened <project>.", "Checked. Name the version, then save.", "Saved as
"<name>".", "Reverted to the saved version. Undo brings your changes back.", and
"Can't open <project>: <reason and path>." Source/labels/diffs render as text.

The editor source owner only reviews/saves files. The adjacent New run controller
uses the saved-source preparation adapter described below; declaration saves
establish neither scientific readiness nor immutable runtime closure. Editor
source inspection never opens referenced resources.

Qualification: targeted `tests/unit/tools/test_workflow_authoring.py` and
`tests/unit/tools/candidate_console/test_editor.py`; real browser:

```bash
EDITOR_PYTHON="$PWD/.venv/bin/python" \
CONSOLE_PLAYWRIGHT_MODULE=/absolute/installed/playwright \
CONSOLE_BROWSER_EXECUTABLE=/absolute/installed/chromium \
node tests/browser/workflow_editor.mjs
```

`tests/browser/capability_layout.mjs` (same variables) opens a five-node authored
loop and checks paper headings, no generic card, pairwise-disjoint cards in light
and dark themes, and full-layout persistence for pointer and keyboard moves;
`tests/browser/circuit_geometry.mjs` checks fallback placement, fit-scale bounds
and overlap detection without a browser. `tests/browser/editor_canvas_fit.mjs`
(same variables) checks at 1440x900 that all five cards are in view after
fit-on-open, that view controls send nothing and keep bytes, folded optional
inputs, the disjoint fully wired interpretation fixture, Tidy up and Undo on an
overlapping layout, zoomed drag arithmetic and a non-empty task panel. `tests/browser/port_legibility.mjs` (same variables) opens the
eight-node families fixture and checks one distinct colour+shape token and readable
pill name per contract, filled/hollow sockets, wire colour, the legend, hover
preview (highlight/dim without selecting), the two-contract refusal, the mapping
chip's field rows and drag-to-connect, without writing the source.
`tests/browser/node_palette.mjs` (same variables; unit owner
`tests/unit/tools/test_workflow_node_edits.py`) checks palette categories/search,
click and drag add, the incomplete-draft Review gate with no disk write, binding the
new node, review/save keeping author comments, drag source and canvas centre both
in view before the drag, refused removal of a node others
read (Delete key), the context menu, byte-identical inspector removal of the added
node, Discard and Undo of a pending dragged node, and cancelling it.
`tests/browser/free_node_drafts.mjs` (same fixture; unit owner
`tests/unit/tools/test_workflow_node_drafts.py`) adds two pending nodes and moves
both (pointer and Alt+Arrow). It wires saved -> pending and pending -> pending,
explains and creates the missing `storage` input in Selection (empty path refused,
undo/redo), and reuses it from the second node's select. It checks that Review stays
blocked while incomplete, then reviews one `node_drafts` proposal with
`document: null` and only inserted lines and saves it with author comments kept.
`tests/browser/palette_guidance.mjs` (same variables and fixture) checks the
stage-ordered compact stack (aligned, touching rows, badges, start guide), accordion
details and typed route chips with receive/send arrows, hover and keyboard popover
content, compatible-port highlighting and its removal, Escape, light/dark text
contrast >= 4.5:1, the narrow drawer, and that nothing is posted or written.

Templates and advice (`editor-templates.js`, `editor-advice.js`,
`editor-templates.css`; server contract in
`tools/workflow_authoring/authoring-contract.md`): the gallery opens from the canvas
header **Templates** button (`#editor-template-open`), the empty-canvas primary action
(`#workflow-start-template`), Home **Start from a template** and the page-bar `⋯` menu
(`window.editorTemplates.open()`). Its dialog lists compact cards (icon, title, one
sentence), first **Blank workflow** (`data-template="blank"`: changes nothing, closes
the dialog and focuses the module search), then the server templates with the graph
preview of the chosen one and loop details collapsed, before **Use template**
(`#editor-template-import`). Use calls `window.workflowEditor.importSource(source,
label)` inside `editorPageBar.quietly(...)`, which runs the ordinary source check
without opening the save step; the result folds into the draft as one undoable step
and Save is still required. Afterwards `editorAdvice.focusFirst()` selects the first
canvas module whose capability has an advice target and focuses its advice field. The node inspector calls `window.editorAdvice.render` directly
after the node heading, so "Your advice to the agents" (multi-line, help,
example placeholder, and under it `.advice-privacy`: "Advice is sent to the model
provider and kept in version history; don't paste secrets.", red-team SEC-2) is its
first input; edits are draft document edits with one
coalesced undo step per node, disabled while a palette node is pending.
`tests/browser/scenario_template_parameters.mjs` (import loop, edit a training
parameter, review, save) and `tests/browser/scenario_template_advice.mjs` (import
the advice loop, write advice, review, save; contrast warning on the plain loop;
documents the B6-blocked three-review aggregation scenario) use the same variables.

The browser test launches a temporary real API/project on its own ephemeral port
and closes it; no provider, GPU or native operation runs. Existing browser
qualification for operations remains separately owned.

## Saved declaration candidate runs

`runnable_editor_projects` defaults to empty and may name only configured
`editor_projects`. `EditedCandidate` in `edited_candidate.py` is the shared
Python adapter for POST `/api/editor/{project_id}/candidate-review` and
`candidate-launch`. Selection contains only prepared operation UUID and expected
saved-source SHA-256; launch adds expected review digest and caller-owned candidate
operation UUID. Saving source never launches work.

The adapter resolves the same verified prepared policy as `CandidateConsole`.
Task manifest, data root, workspace and prepared LLM config observation must match
that context. Actual saved node IDs, explicit input locations and routes come from
source. Selected inputs require the existing native read-only/runtime roots.
Review observes bindings and then name-only credential readiness, without native execution. Native payload
and scientific validation remain launch-time work.

A canonical internal envelope binds full candidate request, captured source and
project/preparation provenance. HTTP returns the digest and curated effects,
excluding raw bridge arguments and source payload. Launch reconstructs bindings and
compares the review digest before loading credentials. Readiness is outside that digest. An existing candidate UUID is looked up first and
must match its admitted source/context/review identities; replay retains the
original capture even after the authoring file or workspace changes. Corrupt
existing admissions fail closed. Clients must retain the same UUID on ambiguous
responses and may inspect it through the existing monitor.


## Operation list

`GET /api/operations` lists operations admitted by this console's own operation
store, most recently admitted first, at most `limit` rows. The owner is
`tools.candidate_operations.list_operations`: it enumerates only
`{state_root}/operations/<UUID>` entries, verifies each through the same
`load_record` path as a single read, sorts by the record's `admitted_at`, and
projects at most `limit` rows through `read_operation`. It creates nothing,
claims nothing, and never launches. A non-canonical entry name or a record that
fails verification (unreadable, invalid JSON, identity or configuration
mismatch) is skipped and counted in `unreadable`, never guessed into a row. At
most 4096 directory entries are examined per request; a larger store reports
`incomplete=true`, and other operations remain readable by UUID.

`OperationListView.operations[]` carries `operation_id`, `kind`, `run_name`,
`project_id` (the reviewed editor project, when recorded), `admitted_at`,
`state`, `native_status` and, for authored loops, the same `LoopStatusView` as
status. Receipts, digests, workspace/log/output paths and credentials are not
part of the projection.

Monitor: `operations-list.js` renders the list as links to
`#monitor/<UUID>`, so selecting a row uses the existing route and Status and
logs owner. It loads once per connection (session revision) when any Monitor
route is shown while connected, including `#monitor/<UUID>`, again whenever the
bare `#monitor` route is entered, on **Refresh list**, and every 10 s while Monitor is
visible, the tab is shown and a listed operation is neither `completed` nor
`operation_failed` (M-4). Each row reads `<project> · <run name> · <local admitted
time>` (ISO and UUID on hover) and states its outcome with the shared
`operationOutcome.sentence`. With advanced tools on, unverified records get a next
step (`python -m tools.candidate_operations status --store-config … --operation-id …`).
Manual UUID entry remains available.

Status and logs (`app.js`): the status line is one `operationOutcome.sentence`
(M-2; native `failed`, `timed_out` and `interrupted` read "Failed: …" in plain words,
and a store `unknown` state whose process reason is `missing_identity` reads
"… is starting."). For a failed operation `#monitor-cause` shows "Cause (from the
log): <last exception line>" (`operationOutcome.cause`, the last line shaped like
`Name(Error|Exception|Failure|Refusal): …`) from the log text already displayed; the
Run page reads the last 64 KiB of the native, then operation, log once and appends the
same line. Loop body counts are singular/plural correct; `state`, `native_status`, process, reason and validation stay in the developer
Operation facts. `#operation-observed` shows local time (ISO and UUID in its title).
After a terminal state (`completed`/`operation_failed`, process `exited`, not
`finishing`) has been read and its log drained to `observed_size`, the operation is
no longer polled (status, log, tokens) and
the line reads `Final status · observed …` (M-5); a 404 `unknown_operation` reads "This
console has no operation with this ID…" and also stops polling (M-3). Re-entering
Monitor or an explicit **Read operation** reads it again. Network failures keep the
"stale" wording. Displayed log text has ANSI CSI sequences removed (M-6; the source log
is unchanged) and `#log-notice` states that logs are shown as written and not redacted
(SEC-1).

## Persistent views, routing and session

`index.html` owns a single document with persistent Home, Workflow, Run and Slow
control sections. `navigation.js` owns `/#home`, `/#workflow`, `/#run`,
`/#monitor` and `/#monitor/<UUID>` (the former `#slow-control[/<UUID>]` is rewritten to the matching
`#monitor` route with `history.replaceState` before routing, so old links keep working); `document.title` names Workflow and
Run. Empty fragments use Home. Complete UUID validation
precedes operation selection; invalid routes show a local error and suspend
operation polling without mutating a native request. Bare Monitor retains
selection; repeated identical UUIDs do not reset the monitor epoch/log cursor.
Back/Forward and internal links hide inactive sections with `hidden`, update
`aria-current`, and focus the active heading on explicit fragment changes.
Polling/theme changes never focus the document. Controllers and DOM are not
reconstructed. `/editor.html` is only an external compatibility entry: its
external `editor-entry.js` replaces the document with `/#workflow`, with a plain
link fallback and no credential form.

`session.js` exclusively owns the Bearer token in closure memory. It exposes
same-origin API requests and connection/revision notifications, never a token
getter. Responses are parsed as JSON only when `content-type` is JSON; a non-JSON
error becomes `Server error (<status>).` and a non-JSON success is refused. A
failed fetch or a non-JSON 502/503/504 marks the console **unreachable** without
disconnecting (token, drafts and intents stay): the collapsed status reads
`Server unreachable. Retrying…` (`.access-unreachable`), a 5 s read-only
`GET /api/choices` probe runs while the page is visible, and the next response of
any kind restores `Connected.`; `console-reachability` events carry
`{reachable}`. `consoleSession.choices()` is the one reader of `/api/choices` and
retains `operationsStoreId`. The single `access-form` captures and immediately clears the password
input. Requests use Authorization, cache no-store and credentials omit; POST
payloads retain their existing owners. No cookie, storage, URL, history payload,
event, cross-tab channel or document-transfer mechanism carries credentials.
Theme enum, optional last-operation UUID and the versioned exact reusable launch
intent are persisted. The launch intent contains only origin/project navigation
context, retained preparation identity, request digest and operation UUID; never
source bytes, native requests or credentials. Operation-bearing records are keyed by the
opaque operations store id: reusable intents (`…v2/<store>/<project>`) and loop
Resume request ids (`siderius.loop-resume.v2/<store>/<predecessor UUID>`; a legacy
`siderius.loop-resume.v1:<UUID>` with the same receipt digest is moved on first use).
Preferences (theme, view flags, tour) and the last-opened operation UUID stay per
origin because they are read before connecting. Settings (advanced) **Forget this
browser's console data** (`browser-data.js`) removes every `siderius.*` key except
records that may name an unfinished operation (reusable intents of other stores or
projects, loop Resume ids); it is disabled while the open project's own retained run is
unreleased (`reusableIntents.clearable()`), asks for confirmation, changes nothing on
the server and reloads the page.
Reload/new tab requires Connect again. Once connected, the access card collapses
on every view to one status line with **Change token** (reopens the form; the
current connection stays until a new Connect) and **Disconnect console** (clears the
in-memory token, bumps the revision and publishes a disconnected state, exactly as a
401 does). Any disconnect reopens the form.

Connect validates through the explicit deep-link operation GET, otherwise choices
GET. Operation 404/409 means unavailable data and does not reject valid access.
A session revision fences prior-connection replies, including old 401s. Current
401 disables effectful controls and labels observations unconfirmed, preserving
drafts, reviewed bytes and submitted UUID/body identities. Editor action eligibility
is derived from the shared session in `editor.js:controls`; request-producing
handlers also refuse disconnected actions. Explicit conflict Discard/Rebase remain
local and usable, but do not restore network actions until authenticated reconnect. Reconnect only refreshes
reads; POSTs never retry automatically. Initial editor/project reads that span a
reconnect restart for the new revision without replacing a loaded pending draft.
Editor projects load only on Workflow or Run entry (Run reads the open project's saved version). Choices/project failures remain local;
known-operation reads need neither task choices nor editor configuration. The one
existing visible-document two-second polling loop retains its cursor/epoch owners.

Home leads with the workflow journey (open the workflow, edit and review, prepare
a new run on the Run page, launch and monitor) and its **Open workflow** action. The native chain
and configured-task flows follow under **Advanced**. All views share one shell:
a compact header (title, about, theme), navigation and content aligned on one
left edge, up to 1920px wide.

Home's configured-task flow is a secondary disclosure independent of the editor
selection. Prepared workspace, identity, routes, limits, devices/network and
credential blockers remain visible before explicit Launch within that flow.
Workflow references, **Advanced source** and **Details** (save behavior and
concurrent-writer notes) start collapsed; successful Review opens the exact diff. Disclosure toggles do not change edit mode or reviewed bytes.
Unsupported-source status and Inspect source remain visible; conflicts retain
visible summary/actions. A `beforeunload` guard applies only to a real document
exit with pending editor changes. Monitor shows operation identity, native
state, observed time and token quality; facts, token rows and logs are disclosures.
It infers neither scientific success nor complete billing.

### Page inventory and guidance

| Route | Primary content and action | Secondary content (Settings-gated unless noted) |
| --- | --- | --- |
| `#home` | Hero (theme-matched logo + one sentence); entry cards **Quick start** (`#home-quick-start`, see below), **Open a workflow**, **Monitor runs** | **Advanced**: native chain card; collapsed **Prepare configured task** (the configured-task quick Prepare form; not a beginner entry, API unchanged for CLI/compatibility) |
| `#workflow` | Page bar (title + dirty badge, project select, task chip, problems chip, Undo/Redo/Revert icons, **Save**, **Next: Run**, `⋯`); save confirmation step (version name, **Save version**); one status line; docked rail, canvas (Templates, bottom-right controls incl. **Tidy up**) and Selection (incl. Research loop) | Task package and version, Version history (collapsed cards below the frame); Exact Python changes, References, Advanced source, Reload from disk, canvas help, connection mappings (advanced); Details (developer) |
| `#run` | Stepper `#run-stepper` (Prepare · Review and launch · Follow in Monitor) and one next-step line `#run-next`; saved-version state; **1 · Prepare** entry `#run-entry[data-run-entry="saved-workflow"]` (**Check inputs** then **Prepare**); **2 · Review and launch** (**Review prepared run** then **Launch run**, inline `#capture-launch-reason`) | Back to workflow; **Run an earlier prepared run instead** (collapsed list); Check status now, operation UUIDs and captured resources (developer) |
| `#monitor` | Recent operations; Status and logs; loop controls; results; token summary | Operation UUID form, Recorded example (advanced); operation facts, token table (developer) |

`page-guidance.js` is presentation only and owns no request or draft state. It reads
`window.workflowEditor.state` and `window.newRunGate.ready`. `new-run.js` remains the
single Run gate: it exports `newRunGate.ready` (its existing `ready()` predicate) and
dispatches `new-run-gate` from its `controls()`. **Next: Run** is enabled
exactly when that gate is open and only sets `location.hash = 'run'`; its tooltip, the
visually hidden `#workflow-next-state` (its `aria-describedby`) and
the Run page's `#run-source-state` show `Saved version "<name>" of project <project> is
ready to run.` when a console Save recorded the open bytes (`editorVersions.nameFor`),
otherwise `The current file of project <project> (version <sha256[:12]>) is ready to
run.` (a never-saved file is never called a saved version, red-team A-6/A-7), or the
first closing reason (not connected, no project, source not
open, project not runnable, not a reusable declaration, conflict, saving, unsaved
edits). Those reasons explain a closed gate and never open it. The New run and
Prepared run controllers keep their element IDs and behavior; their task loaders run
on Workflow or Run entry. `reusableCandidate.openPrepared` routes to `#run` instead of
opening a disclosure, and scrolls to the capture heading only after the
`console-view` event shows the Run panel (next animation frame).

**Quick start** (`quick-start.js`): Home `#home-quick-start` routes to `#workflow` and
opens `#quick-start-dialog`, whose **Project (its task and data)** select mirrors the
editor's own `#editor-project` options, runnable projects first; an edit-only project
is labelled and warns "You can edit this project but not run it from this console."
(L-7). **Open research loop** first reads the project (`GET /api/editor/<id>`): a
failure shows "Couldn't open <project>: <reason>" in the dialog and keeps the button
for a retry; a project that then does not finish loading within 20 s shows the
editor's status instead of hanging (L-3). After the import, focus moves to the first
advice field (L-6).
**Open research loop** selects that project through the editor's ordinary project
change (its pending-edits confirmation applies), waits for the saved source, then calls
`editorTemplates.importById('single-research-loop')`, the gallery's existing import
path: an unsaved draft, nothing written before Save. No task declares its own template
yet, so that catalog entry is the default for every task. Rounds, stop conditions and
training settings are then edited in the ordinary panel. The Run page's step-1 entry is
one section (`#run-entry`); steps 2-3 read only the `reusableCandidate.openPrepared`
handoff, so another entry can replace it. When this page created a preparation, the
first observed `prepared` status opens it in step 2 once (a read-only `/select`); Review
and Launch stay explicit. A store `unknown` state without a receipt reads "Preparing…"
(process reason `missing_identity`) or "Checking status…", never as a finished failure
(B8-2). Step 2 names the version its prepared run holds (`ReusableCaptureReview.
source_version_name`, display-only `recorded_name` of `source_sha256`, or before review
the preparation intent's `source_version` handed over by `openPrepared`); when it is not
the current saved version, `#capture-source`, the top `#run-source-state` and `#run-next`
say so and `#capture-prepare-current` ("Prepare the current version instead") starts
step 1 over (B8-3). Step 1's Start over (and that button) dispatches `run-start-over`,
which clears step 2's selection and review unless a launch is retained, so an older
capture is never left ready to launch (B8-4).

Until the canvas draws a capability card, the canvas panel shows the empty start state
`#workflow-start-guide` (spec §7.2): title **Build your research loop**, one sentence from
`page-guidance.js` (`#workflow-start-state`: connect, choose a project, source not open, or
add a module), one primary action **Start from a template** (`#workflow-start-template`,
opens the gallery; disabled until connected) and the tour as a secondary link
(`#onboarding-start.link-button`). CSS hides it with
`.workflow-canvas-panel:has(.circuit-card)`. The Selection panel shows `.inspector-empty`
until `.inspector-capability-heading` exists. The page-bar `#problems-chip` mirrors the
`.editor-problem` count that `editor-problems.js` renders (MutationObserver; hidden at 0)
and focuses the first problem. A step line (`#step-indicator`, `role="navigation"`, not a
`<nav>` element) shows Task › Workflow › Run › Results on Workflow (Task until a source is
open), Run and Monitor, with `aria-current="step"` and a done mark for completed steps; it
is hidden on Home. Witness: `tests/browser/page_guidance.mjs`.

### Layout system, Settings and onboarding

Owner of tokens: `theme.css`, adopted from `ui-design-spec.md` §1–§2: spacing
`--space-1..7` (4/8/12/16/24/32/48 px), `--bar-height` 48 px, `--control-height` 36 px,
radii `--radius-1/2/pill` (4/8/999 px), `--elev-0/1/2` (elevation only for overlays and
movable canvas cards), type `--font-title` 20, `--font-heading`/`--font-body` 14,
`--font-label`/`--font-help` 12 px (`--font-prose` 16 px for the Home sentence), no
all-caps labels. Light accents (`--primary #2e6da6`, `--secondary #0f7672`,
`--error #c4304a`, `--warning #85600c`) keep 4.5:1 text on the page, panels and every
capability tint. `styles.css` owns the shell and card component: header, nav and content
share `--shell-pad`; every view is one grid column with `--space-4` gaps; a `.card` is
bordered (`--radius-2`, no shadow) and a direct `h2` is its header above a divider;
`details.card` summaries are equal-height header bars whose divider appears only when
open. `editor.css` owns the Workflow frame: page bar, then the docked
`.editor-workspace` grid `var(--rail-width) 272px | canvas | var(--inspector-width) 352px`
(320 px below 1280 px), height `--workspace-height` (set by `editor-page-bar.js`: window
height minus the frame's top when scrolled to the top, minus 16 px, at least 480 px; the
open save step is not subtracted), 1 px dividers and no gutters; rail and Selection
scroll independently under a sticky 48 px header; the canvas panel does not scroll, its
`.circuit-viewport` fills the remaining height and scrolls (`editor-page-bar.css`). Below 900 px the panels
stack at natural height and the rail is `editor-palette.js`'s drawer. The rail column is
`--rail-width`; s9's collapsed icon rail may set it to 48 px.

Logo: `siderius-logo-light.svg` (navy wordmark) and `siderius-logo-dark.svg` (white
wordmark) are exact-allowlisted `image/svg+xml` assets (shapes plus an embedded PNG, no
script) rendered only through `<img alt="SIDERIUS">`. Each place carries both images;
CSS shows the variant matching `data-theme` (theme.js resolves System). The header logo
is 30 px high; the Home hero logo 72 px. The response CSP adds `img-src 'self'` for them.

Settings (`ui-settings.js`, loaded in `<head>` before styles so the first paint is
already filtered): flags `advanced` ("Show advanced tools") and `developer` ("Show
developer details"), default off, stored as `siderius.console.ui.<flag> = "on"`
(storage denial keeps the page default). The module sets `data-ui-<flag>="on"` on the
root; `styles.css` hides any `[data-ui-flag~="<flag>"]` element otherwise. API:
`window.uiSettings.isEnabled(flag)`, `.set(flag, enabled)`, `.flags`; event
`ui-settings-change` `{flag, enabled}`. The header **Settings** button opens a
non-modal panel with the two checkboxes (Esc closes). Flags change visibility only: no
request, draft or run state; hidden sections keep their state. Witnesses that exercise
gated sections call `showAllConsoleSections(browser)` from
`tests/browser/console_view_flags.mjs`.

Tour (`onboarding.js`, spec §7.3 within its 3–4 step limit): opt-in only, from the empty
canvas link, the header **Help** button or the page-bar `⋯` menu; from another page it
switches to `#workflow` first. Four steps, each highlighting a visible element with an
outline ring and a non-modal card placed beside it (right, below, left, above, clamped;
no backdrop, the page stays usable): **Choose a task** (`#editor-project`), **Pick a
module** (`#editor-palette`), **Match connector names** (`.circuit-viewport`), **Save a
version** (`#editor-review`, the page-bar Save). Buttons Skip · Back · Next / OK; Esc = Skip; focus returns
to the opener. Outcome `done`/`dismissed` is stored as `siderius.console.tour.v1`; it
never reopens itself. Witness: `tests/browser/layout_onboarding.mjs` (defaults, Settings
toggles and persistence, tour anchoring/non-blocking/reopen, logo per theme, docked frame
geometry at 1440×1100 and 1024×768 in both themes, card disjointness, page-grid edges,
text ≥ 4.5:1 and ≥ 12 px outside the canvas, rail and inspector internals).

#### Workflow page bar, save step and canvas controls

Owner: `editor-page-bar.js` / `editor-page-bar.css` (presentation only; reads
`window.workflowEditor.state`, never mutates a draft or sends a request).

- Connection (spec L6): `#access-section` lives in the header. Disconnected it is a
  full-width banner (heading, token form, status); connected (`session.js`
  `.access-collapsed`) it is one chip: `#access-status` **Connected.** (tooltip: the
  2 s observation refresh), **Change token**, **Disconnect console**.
- Page bar, left to right: `h1` + `#editor-dirty`; `#editor-project` (label visually
  hidden); `#editor-task-chip` (`Task: <package_id> · <revision>`, `Task: not bound` or
  `Task: not open`; `needs-attention` while a bound workflow has no selected configured
  version or task findings are pending; click opens `#editor-task-panel`, a collapsed
  `details.card` below the frame holding the unchanged `editor-task-controls.js` panel,
  open by default when advanced tools are on); `#problems-chip`; `#editor-edit-actions`
  (Undo `undo-2`, Redo `redo-2` icon buttons created by `editor-draft.js`, names via
  `aria-label`; **Revert to saved** keeps a visible label beside its `rotate-ccw` icon so
  it never reads as a second Undo, red-team A-5); Reload from disk (advanced);
  `#editor-version-tag` beside the project select (tour #18): the version name of the
  open bytes, or "Not saved here yet" for a file without a console-saved row, plus a
  dirty dot while edits are unsaved;
  primary **Save** (`#editor-review`); **Next: Run** (`#workflow-next-run`); `⋯`
  (`details.overflow-menu`: New from template…, Take the tour, Task package and version,
  Version history, Advanced source (advanced only), Settings…).
- Save step: **Save** is the ordinary editor Review (unchanged request and gating).
  When a check succeeds (`state.reviewed` turns true) the in-flow
  `#editor-save-confirm` row opens under the page bar with `#editor-version-name`,
  **Cancel** and **Save version** (`#editor-save`, unchanged: it posts exactly the
  checked `reviewed.source` bytes with their sha256). It closes on Cancel/Esc, on any
  edit (the check is invalidated) and after Save. A pending task review adds
  **Show task findings** (opens the task card for the acknowledgement). The diff
  (`#editor-review-disclosure` › `#editor-diff`) is an Advanced disclosure in the row.
  Template imports run inside `editorPageBar.quietly()` and do not open it.
  `workflowEditor.state` gained presentation fields `reviewed`, `taskReview`,
  `taskSelected` and `taskBinding` (`{package_id, revision}` or null).
- Canvas (at least 900 px wide): the canvas header holds **Templates**; the panel is a
  flex column with `overflow: clip` (never scrolled, not even by `scrollIntoView`) whose
  `#editor-graph` (`flex: 1 1 0`) grid gives `.circuit-viewport` exactly the remaining
  height; the viewport scrolls and zooms inside it, so Fit fits the visible viewport.
  Open disclosures in the panel (port-type legend, canvas help and connection
  mappings 120 px) scroll internally. Invariant (witnessed by `layout_onboarding.mjs`
  and `first_use_journey.mjs`): viewport inside the canvas panel, viewport height ≤
  workspace height, panel `scrollTop` 0. The circuit toolbar sits bottom-right of
  the canvas and the connector legend bottom-left. The wire layer is the world's own
  child `<svg>` (`.circuit-world > svg`; never the first `svg` of the canvas, which may be
  a toolbar icon) with `pointer-events: none`; only `.circuit-wire-target` strokes take
  pointer hits, so cards and ports stay hoverable and wires stay clickable. A drag
  released over an input binds the input whose own box holds the release point,
  preferring a highlighted (compatible) one, then swallows the browser's own click that
  follows the release; contract pills are clipped to their port. Rows above the viewport
  have a fixed height (the status message is always two clipped lines and Disconnect
  shares its row), so a new message never moves the ports under the pointer mid-drag. Below 900 px the panels keep
  their natural height (no `--workspace-height`). **Tidy up** (`#circuit-tidy`,
  `layout-grid`) places every module with `editorCircuitGeometry.tidy`: columns by
  longest result-input path from a source, rows by the mean row of the sources (ties
  by pipeline stage: literature, interpretation, proposal, implementation, validation,
  tuning, then id); modules with no wire take the next column in stage order, and with
  no wire anywhere they form one row in stage order; steps = largest card + 80/32 px
  rounded up to 16 px, all on the 16 px grid. It is one draft edit through the
  ordinary `move` callback (label `Tidy up layout`, undoable, saved only with Save).
- Check the workflow (`#circuit-check`, `repeat-2`; `editor-circuit-walk.js`): `plan`
  orders the displayed nodes sources-first and lists one step per result-fed input,
  then the loop feedback; the first required, non-framework-supplied, unbound input
  (or a loop whose endpoint is gone, or an empty canvas) is the break. `run` moves an
  HTML token (`.circuit-walk-token`) along each drawn wire path (220-900 ms per wire),
  then marks the break socket `.walk-break` (soft red halo, three gentle pulses, a few
  px around the 12 px socket, never larger than the card) with one sentence
  `#circuit-walk-note` under the card ("Implement can't start: Model plan is not
  connected."). `prefers-reduced-motion: reduce` skips the token and the pulse; the
  halo and note show at once. The viewport carries `data-walk-state` running /
  complete / break; any re-render clears it. It derives no validity of its own.
- The research loop's feedback is drawn as a dashed display-only path
  (`.circuit-feedback`) from the feedback module's output over the cards to the target
  module's heading.
- Keyboard and screen readers (red-team E-7): `#skip-to-canvas` is the first Tab stop
  on the Workflow view (hidden on other views) and focuses the selected (else first)
  module heading or the viewport without changing the route. Wire targets are named
  `<module> sends <connector> to <module>`, are in the Tab order only with advanced tools
  on (`tabindex -1` for beginners) and show a soft focus halo along the stroke. Unknown
  hash routes are replaced by `#home` (navigation.js); a malformed `#monitor/<id>` stays
  on Monitor with "Invalid operation UUID".
- `+` add-handle (`editor-canvas-add.js`, canvas-study V5): an output whose card feeds
  no wire, and whose contract at least one catalog route accepts, shows a 20 px `+` 8 px
  outside the card while the card is hovered, focused or selected (no dead `+`; the
  handles re-sync on the `editor-node-catalog` event after the catalog loads). It opens a search popover of catalog routes that have an argument with the
  output's contract id (`editorNodePalette.connectable`, presentation filter only).
  Choosing one calls `editorNodePalette.addConnected`, which adds a pending node 80 px
  right of the source with that argument (required first) bound to
  `{kind: 'result', node, port: 'result'}` as ONE draft edit (`Add module <id>`);
  the server node inspection decides completeness as for palette adds. Esc closes.
- Research loop is a section of the Selection panel (`#editor-loop.inspector-section`).
- Sockets (tour review batch 1): the visible socket label is the connector (schema) name
  from the server catalog in 12px label style (`.circuit-port-contract`), followed by
  `Required`/`Optional` and ` · Not connected` when unbound; protocol field names appear
  only in the advanced Mapping details and as an advanced `code` chip in inspector rows,
  which read `[swatch] <connector name> · Required` (`editor-inspector-rows.js`). Sockets
  carry no `title`; `editor-circuit-tooltip.js` shows the §6.3 socket tooltip (swatch +
  name, the server description, "Connects with: <module names>" from the server-offered
  choices, "Required." when unbound) after 300 ms or on keyboard focus, hides on leave
  (150 ms), blur, Esc, scroll or re-render, and never takes pointer events. A refused
  connection's reason is kept as `data-refusal` on the dimmed input. Icon-only canvas
  controls get a one-line tooltip from `data-tip-label`.
- Cards fold every optional input that is not fed by a wire (not connected, or fed by an
  external input) into one `+N optional` row. Fit to view never zooms below 75%; a larger
  graph scrolls inside the viewport and the view note says "Scroll the canvas". Manual
  zoom out still reaches 40%.
- Canvas controls are one secondary icon cluster bottom-right (zoom out, zoom %, zoom
  in, Actual size, Fit, Check the workflow, Tidy up); the connector legend is a bottom-left
  chip whose content opens as a two-column popover above it.
- Problems (spec §9): `#problems-chip` (`circle-alert` + "N problems") toggles the 320px
  `#editor-problems` popover under it; it never takes space in the page. Each row is one
  sentence `<module name>: <connector name> is not connected` (other codes:
  `<module name>: <server message>`; source diagnostics `Python source line N: …`), with
  the raw located diagnostic as an advanced `code`. Row click closes the popover and
  selects the node and field. Esc or an outside click closes it. Status lines are one
  plain sentence and never repeat the problem list. After undo, redo and Discard the
  problems are recomputed from the restored state's cached server inspection (or
  re-inspected).
- Unconnected required input (operator rule 2026-10-28): the socket itself shows a soft
  red ring (`--error`, 28% ring) and its `Required · Not connected` text is `--error`; the
  card keeps its normal outline and carries only a count badge (`.circuit-problem-badge`,
  text = count, `aria-label` "N required input(s) not connected"). Connector labels wrap
  inside the card; the requirement text is its own line. Instance ids show only with
  advanced tools. Wire and card drags suppress text selection (`body.circuit-gesture`,
  `preventDefault` on pointerdown, selection cleared at the end).
- Framework-supplied inputs (operator rule 2026-10-28): `PortInventoryEntry.framework_supplied`
  marks a socket bound to a `ManagedCandidateBinding` in a role candidate preparation
  generates (`candidate_prepare.resolution.managed_argument_roles` /
  `managed_request_supported`: per-node `storage`, tuning `settings`, a proposal's
  `proposal.input` request; for `native-interpretation-candidate/v1` also `data_dir`,
  `task_composition_ref`, `human_advice`, `expert_context`, `constraint_context`,
  `workflow_parameter_rules` and the interpretation request). Such sockets get no canvas
  socket, inspector row, problem, walk-through stop or "Create external input"; the
  advanced Mapping details still list them. `SourceView`/`ReviewView.managed_roles` lists
  the required roles a new node gets: any add (palette, `+`, template) binds them in the
  same draft edit as the shipped examples do (`editor-managed-inputs.js`):
  `ManagedCandidateBinding(id="<node>_store", contract="storage")`,
  `id="training"` for `native-training.settings`, `id="initial"` for `proposal.input`
  (a taken id falls back to `<node>_training` / `<node>_initial`, then a number). v1
  sources have no managed roles: their storage is a real input the author supplies.
  Deleting a node also drops managed bindings only it read (preparation refuses unused
  bindings). Gallery **Blank workflow** deletes every module in the draft (undoable)
  and shows the empty state. Witness: `tests/browser/managed_storage.mjs` (Blank on
  the reusable project, Propose/Implement/Validate without any storage input, saved
  binding shape equal to `examples/workflow_declarations/reusable_candidate.py`).
- Delete (operator rule 2026-10-28) always succeeds in the draft, with no confirmation:
  Delete key, context menu or Remove in Selection adds saved nodes to the draft's
  `removed` list (pending nodes are cancelled), disconnects every socket that read them
  (binding patches / pending bindings; a required one becomes a `required_unbound`
  problem), and Undo restores everything. The draft is inspected as a `node_drafts`
  proposal with `removed` (`workflow_authoring.models.NodeDraftsProposal`); the server
  adds `loop_feedback_missing` when a loop endpoint is deleted and `workflow_empty` when
  no module is left, and Review/Save refuse (`draft_incomplete`) until no problem
  remains, so the saved file is never invalid. A deletion nobody reads, with no other
  edits, is a targeted byte-preserving removal; otherwise the combined document is
  rendered canonically. Deleting every module shows the §7.2 empty state.
- Disabled Save shows `#editor-save-reason` inline ("Fix N problems to save",
  "Checking…", "Saving…"); disabled Next: Run shows `#workflow-next-reason` ("Save a
  version to run" or "Not set up for runs").
- 900–1279 px: the module rail is a 48 px column with one icon button; it opens the full
  272 px rail as an overlay over the canvas.
- Templates are complete fixed shapes. Every template renders a reusable document whose
  execution profile admits no extra module (the interpretation loop requires "one
  interpreter and complete candidate"; the single step "exactly one proposal,
  implementation and validation"). Their only free output is Train & tune, which no
  catalog route accepts, so a template shows no `+`; its next step is advice and
  parameters. `+` adds modules in free-form (schema 1) workflows. Adding modules to a
  template shape needs a server-side profile change (not in this change).
- Icons (spec §3): vendored Lucide sprite `static/icons.svg` (47 `<symbol id="i-NAME">`,
  shapes only, licence `static/icons-LICENSE.txt`, ISC + MIT for Feather-derived
  icons), exact-allowlisted as `image/svg+xml`. `icons.js` fetches it once, adopts only
  its `<symbol>` elements into a hidden in-document `<svg>` and exposes
  `consoleIcons.make(name, size)` / `.decorate(root)` (`data-icon="NAME"`); icons are
  `aria-hidden`; if the sprite cannot load, controls keep their text. Capability icons
  (`editor-capability-presentation.js`) use §3.3: literature `book-open-text`, proposal
  `lightbulb`, implementation `code-xml`, validation `shield-check`, tuning
  `sliders-horizontal`, interpretation `chart-spline`, fallback `shapes`.
- The page footer line was removed.

Witnesses: `tests/browser/first_use_journey.mjs` (beginner first use at 1440×1100:
Home → connect → Home template → Blank workflow first → module search focused → `+`
adds Implement wired → drag and Tidy up without overlap → Create external input → Save
step (Cancel, Save version); then the runnable project: Templates → Use template →
advice focused → no `+` on the fixed shape → Tidy up → Save version → Next: Run; canvas
visible without page scroll),
`page_guidance.mjs`, `layout_onboarding.mjs`; `circuit_geometry.mjs` covers `tidy`
in Node.

#### Feature inventory (Beginner / Advanced / Developer)

Default view = Beginner. `data-ui-flag="advanced"` sections appear with Settings ›
**Show advanced tools**; `data-ui-flag="developer"` with **Show developer details**.
"Gated" = gated in this change (s11-owned markup); "Hook" = sibling-owned content for
the spec conformance pass to gate with the same attribute or `uiSettings.isEnabled()`.

| Page | Control / section | Class | Status | Reason |
| --- | --- | --- | --- | --- |
| Shell | Logo, nav, Connect / Connected line, theme, Help, Settings | Beginner | shown | Needed to reach any page and to get help |
| Shell | About this console | Beginner | shown | One-line orientation, collapsed |
| Shell | Step line Task › Workflow › Run › Results | Beginner | shown | Tells a new user where they are |
| Home | Hero: logo + one sentence | Beginner | shown | Says what SIDERIUS does |
| Home | Entry cards: Start from a template, Open a workflow, Monitor runs | Beginner | shown | The three first actions |
| Home | Run a configured native chain | Advanced | gated | Externally reviewed captures; not a first-use path |
| Home | Prepare configured task (native Prepare / Launch candidate) | Advanced | gated | Server-configured route independent of the editor |
| Workflow | Page bar: title, project select, version tag + dirty dot, task chip, problems chip, Undo/Redo icons, Revert to saved, Save, Next: Run, `⋯` | Beginner | shown | Edit → save → run loop |
| Workflow | Version history (View, Restore this version as a draft) | Beginner | collapsed card; `⋯` › Version history | Go back to an earlier saved version |
| Workflow | Save step: version name, Save version | Beginner | shown after Save | Confirms a named version of the checked bytes |
| Workflow | Reload from disk (toolbar) | Advanced | gated | Only for external edits to the source file |
| Workflow | Status line (editor status, pending edits); Run gate reason as the Next: Run tooltip | Beginner | shown | Explains what happened and why Run is closed |
| Workflow | Problems list (`#editor-problems`) | Beginner | shown | Required inputs to fix before saving |
| Workflow | Source conflict card (Reload from disk / Reapply my changes onto latest; whole current file advanced) | Beginner | shown when a conflict exists | Must stay reachable to resolve a conflict safely |
| Workflow | Workflow project select and task chip (page bar) | Beginner | shown | Choose a task |
| Workflow | Task package and version details (choose version, update references, findings) | Beginner | collapsed card below the frame; open by default with advanced tools | Opened from the task chip when a version must be chosen |
| Workflow | Module rail (palette) | Beginner | shown | Add modules |
| Workflow | Canvas, bottom-right controls (Fit, zoom, Check the workflow, Tidy up), `+` add-handles, empty-canvas start state, Skip to canvas | Beginner | shown | Build and connect |
| Workflow | Canvas controls help (keyboard-move hints) | Advanced | gated | Long control reference; the tour covers first use |
| Workflow | Connection mappings list | Advanced | gated | Protocol detail per binding |
| Workflow | Templates button and gallery (Blank workflow first, Use template) | Beginner | shown | One-click start from a simple closed loop |
| Workflow | Module rail start guide, stage stack, row details, hover/focus popover | Beginner | shown | Where to start and what connects to what |
| Workflow | Contract legend (swatch + name, arrow key) | Beginner | shown | Same name = connectable |
| Workflow | Raw contract ids in the legend | Advanced | gated (`editor-contract-presentation.js`) | Catalog identity, not needed to connect |
| Workflow | Mapping chips ("adapter") on cards, card Mapping details | Advanced | gated (`editor-contract-presentation.js`, `editor-circuit.js`; flag change re-renders the canvas) | Protocol field mapping |
| Workflow | Selection inspector, in order: advice (`editor-advice.js`), inputs with contract names, "Create external input" (`editor-external-inputs.js`), training and loop settings | Beginner | shown | Configure the selected module |
| Workflow | Inspector Mapping details, model-hyperparameter owner (`editor-node-parameters.js`) | Advanced | gated (`editor.js`, `editor-node-parameters.js`) | Protocol / task-manifest detail |
| Workflow | Delete module (trash icon in the Selection header) | Beginner | shown | Undo a placement |
| Workflow | Research loop (Selection section) | Beginner | shown | Iteration limit and stop conditions |
| Workflow | References (task / external locations) | Advanced | gated | Paths owned by the task configuration |
| Workflow | Advanced source (Python editor) | Advanced | gated | Direct source editing |
| Workflow | Exact Python changes (in the save step) | Advanced | gated | Byte-level review of what Save writes |
| Workflow | Version history SHA-256, record path, whole saved Python | Advanced | gated | Byte-level identity of each version |
| Workflow | Details (save behavior, concurrent writers) | Developer | gated | Implementation notes |
| Run | Saved-version state, New run (task, name, Review preparation, Prepare saved source) | Beginner | shown | Prepare the run |
| Run | Selected source, inputs and resource limits | Beginner | shown | What will run |
| Run | Prepared run (open, review, Launch captured run) | Beginner | shown | Start the run |
| Run | Captured resources and version | Developer | gated | Raw capture record |
| Monitor | Recent operations, Status, loop Stop/Pause/Resume, training results | Beginner | shown | Follow a run and read results |
| Monitor | Activity and logs | Beginner | shown | Explains failures |
| Monitor | Reported LLM tokens summary | Beginner | shown | Cost awareness |
| Monitor | Operation UUID form, remembered ID | Advanced | gated | Opening an operation not in the list |
| Monitor | Operation facts | Developer | gated | Raw native/operation fields |
| Monitor | Reported token table | Developer | gated | Raw per-model rows |
| Monitor | Native chain observation details | Advanced | hook (native-chain-monitor.js) | Native recipe internals |
| Monitor | Recorded example | Advanced | gated | Read-only validation evidence |

Not yet adopted from the spec (follow-up, not in this change): Help menu (§7.4 shows
only the tour), Lucide icons for the header gear/help and the step line, project/task in
an inspector Workflow tab (L5; the task details are a card below the frame), tour
backdrop (omitted so the page never blocks), canvas internals below 12 px, minimap,
connection snap radius, palette click-to-add auto-wiring (P6) and Connection view (R3).

Navigation qualification: `tests/browser/console_navigation.mjs` uses the same
explicit environment as the editor gate. Its temporary synthetic observations
cover direct operation reads without editor access, invalid UUID refusal,
remembered-ID precedence, history/cursor/poller preservation, failed project
isolation, connection races/401 and pending-draft/reload behavior. Existing editor,
console and theme browser harnesses exercise the shared shell and disclosures.
These are local browser witnesses; they do not qualify native execution, complete
circuit editing, results, resume or production deployment.


## Reusable capture consumption

`TaskChoice.reusable_runs_root: str | None = None` opts a task into discovery.
The configured existing canonical parent must lie within both explicitly supplied
operation-store preparation and candidate roots, and remain separate from state
and editor recovery. No roots are added automatically. The field is excluded from
legacy `preparation_request`; legacy separate destination mapping is unchanged.
`runnable_editor_projects` remains the project execution opt-in.

`ReusableCandidate(console)` is the shared Python and HTTP adapter. Models live in
`reusable_models.py`; `reusable_policy.py` owns console admission comparisons.
GET `/api/editor/{project_id}/reusable-captures?task_id=...&cursor=...&limit=25`
enumerates direct canonical UUID names in lexical order, not creation order. Limit
is 1–100; memory and metadata reads are page bounded. Directory enumeration is a
single direct scan without a recursive index/watcher. Unavailable/malformed entries
remain descriptors and cannot suppress other entries. Availability means metadata
can be inspected under policy, not complete preparation or native acceptance.

POST suffixes `/select`, `/review`, `/launch` use `ReusableCaptureChoice`,
`ReusableCaptureSelection`, `ReusableCaptureLaunch` respectively. Select receives
only task ID and run UUID; the server derives the path. A retained selection must
match that exact derived path before reads. Preparation-owned binding inspection
checks bounded receipt/binding/control metadata before console compares project,
original source path, task manifest, data root, original LLM config, read-only
paths, both timeouts, network, devices, environment names and every control source
path. Current authored source bytes are never re-read for capture selection.
Configured output restriction None is unconstrained; otherwise exact tuple equality
is required, including order. Captured advice/run name remain captured inputs.

Complete preparation verification and B2 builder remain mandatory after policy.
Review exposes curated paths, graph/routes, advice/resources, source/composition
identity and name-only credential readiness. `operation_request_digest` publicly
aliases the existing operation digest; no new serialization or UUID-dependent
identity is introduced. Fresh launch rechecks policy and retained capture, compares
digest, then reads credentials and calls `submit_operation`. B2 admission/dispatch
rechecks remain unchanged. Credentials are excluded from review identity.

Launch looks up the candidate UUID before any project/task/capture/credential
admission work. Existing kind, retained preparation selection and owner digest
must match; recovery submits the durable record with an empty environment. It
claims only admitted operation identity/status, not current project/source labels.
Store-config equality and static containment remain enforced by the operation
owner. Corrupt/conflicting lookup is not absence. Required configuration files
are still validated at server startup; file-independent recovery is a live-service
property, not permission to restart with missing required resources.

`ReusableAdmissionNotAttempted` is raised only before entering `submit_operation`.
HTTP adds `error.admission_not_attempted: true` for that exception. This certifies
that dispatch did not call admission; it is not global proof a UUID can never be
claimed by another caller. UI dismissal is offered only on the initial live POST
receiving this signal. Restored, retried, conflicted or ambiguous requests never
become dismissible through it. No operation-owner semantics or registry changes.

`reusable-run.js` retains one exact launch intent in localStorage before POST and
checks readback. Failure prevents POST. Pending intent is keyed by store and project
(below), so switching task/selection cannot overwrite it. While the Run view is
visible and connected, both Run controllers read their retained operation every 2 s
(paused while the tab is hidden) and once on load, reconnect and Run entry; polling
stops on release, on an initial refusal and on `unknown_operation` (Retry restarts
it). `reusable-run.js` also reads the retained preparation's status on load/connect so
Launch eligibility never waits for a manual check (R-2); a disabled Launch shows its
first reason inline in `#capture-launch-reason`. Retry is the only re-dispatch and is
offered only for an unresolved or unknown outcome; reconnect never submits.
Completed or eligible initial refused intent requires explicit dismissal and storage
readback confirmation. Operation sentences come from `operation-outcome.js`
(`operationOutcome.sentence`), shared with Monitor. Monitor uses existing
Slow-control status/log/token routes and native accepted/rejected states.

Editor projects/source state are exposed through a read-only projection/event:
project ID, enabled flag, saved digest, source availability, dirty draft and conflict
facts. Draft changes update comparison only; project/task/capture changes fence
reviews by generation. Session revision fences prior-connection replies. Disconnect
clears review content and disables network actions while preserving editor drafts
and pending operation identity. No Bearer token enters the projection/storage.

Qualification: focused console reusable policy/order/HTTP/recovery tests and
`tests/browser/reusable_candidate.mjs` using the same explicit Python/Playwright/
Chromium environment as the editor gate plus optional `CONSOLE_EVIDENCE_DIR`.
The real offline browser witness uses real preparation/HTTP/detached/native sandbox
CPU validation and a local deterministic provider with fail-closed URL/proxy guards.
It is not paid-provider, training, scientific-quality or production qualification.


### Monitoring detached reusable preparation

Known operation status accepts `kind="prepare_reusable"` from the shared operation
owner. The console projects the reusable receipt's native `preparation_id`, not its
envelope `run_id`; candidate validation remains null. Logs and preparation token
not-applicable state use existing operation accessors. The legacy preparation
review action remains restricted to `kind="prepare"`. Code/CLI users select a
successful reusable envelope through the existing configured prepared-capture
flow. The New run adapter below consumes this monitor without adding job persistence.


## New run from saved reusable source

`ReusablePreparation(console)` in `reusable_preparation.py` exposes
`review(project_id, NewRunSelection)` and `prepare(project_id, NewRunIntent)`.
POST `/api/editor/{project_id}/reusable-preparations/review` returns `NewRunReview`;
POST `/prepare` returns existing `OperationHandle` with HTTP 202. `NewRunReview.source_version_name`
(omitted when absent) is the recorded Save name of `expected_source_sha256`,
display-only and outside the expectation and native request. `NewRunReview.credential_readiness`
is a name-only precheck read in the server process before Prepare: it checks only the
task's configured `candidate_environment_names` against `credential_file`
(`named_credential_readiness((), names, path)`); provider-derived requirements exist
only after preparation, so capture review and launch recheck them. It is outside the
expectation and never blocks Prepare. Review also refuses (409 `launch_policy`, the owner's message
forwarded verbatim) a workflow whose authored training settings omit
`healthgate_mode` or `result_authority` or declare `observe_only` + `scientific`: it
calls `execute_tools.health_checks.launch_policy.validate_declared_policy` (refusals
1-3 of `validate_formal_launch`) on the same sparse payload preparation captures
(`settings_payload`). Config-dependent refusals 4-6 still run at training admission.
Prepare reuses the same review, so the refusal there carries
`admission_not_attempted`. The browser keeps the version name
as `source_version` beside, not inside, the retained intent payload. Both use the
same authentication/origin/body boundary and threadpool transport as capture APIs.
Selection accepts only task_id, run_name, run_id, preparation_operation_id and
expected_source_sha256. Intent adds native `ReusablePreparationExpectation`;
no browser paths/resources, source bytes or credentials are accepted.

Fresh review/prepare resolves configured project/task/root, builds the native
request, invokes preparation-owned `inspect_reusable_source`, compares the shared
`check_request_policy`, then performs full native preflight and rechecks policy.
`None` output restriction is unconstrained; explicit tuples require exact equality.
The source-only helper can inspect path metadata but reads only configured source
content. Unconfigured task references fail before manifest/config content reads.
Full preflight owns actual observations; owner request digest and ordered typed
observations form the expectation. Review creates no directories or task imports.

Prepare recovers durable UUID/expectation before mutable project/task/source policy.
Known records also require retained run UUID/name/source digest to match native
request metadata. GUI project/task labels are navigation context, not durable native
admission fields. An exact recovery submits the durable operation with empty
environment and same expectation. Unknown/corrupt/conflicting records are not absence.
Absent UUIDs repeat fresh source policy/preflight, compare the retained expectation,
then call submit; owner fresh-preclaim observation checks remain authoritative.
Only console pre-submit failures get `admission_not_attempted`; recovery or submit
failures never get that signal. Preparation never reads credentials.

`new-run.js` requires saved parsed v2 source, enabled project, digest, no draft,
conflict or save in flight. Task starts at an explicit blank placeholder. It allocates
run/preparation UUIDs once for the current form and retains them across reviews.
Editor projection adds `reusableSource` and `saving`. Generation/project/session
fences invalidate stale task/review responses. Pending intent survives form/source
changes. Successful preparation is not automatic candidate dispatch.

`reusable-intents.js` coordinates only the candidate and preparation records, keyed
by the opaque operations store id from `/api/choices` and the editor project:
`siderius.reusable-{candidate,preparation}.v2/<operations_store_id>/<project>`
(payload unchanged: version/origin/project/exact intent). A record of another store or
project is never read, checked or blocking here (`eligible()` covers only the current
pair). A legacy per-origin `…v1` record whose `project` equals the current project is
moved once under the current store's key on first context; it is then checked
against this store like any other record. Without a known store id and project no
record is read and Prepare/Launch stay disabled.
Before dispatch/retry/state update/dismissal, stored serialization must equal the
retained record. Readback failure prevents POST. Release evidence is in memory,
requires matching kind/UUID/request digest, and is cleared by storage events.
Completed/operation_failed plus exited process, or confirmed spawn_failed, permits
release; finishing/unknown/alive does not. Only initial live pre-submit refusal
permits refused-intent dismissal. Restored/retried/404 `not_found`/transport
outcomes retain identity. **Forget** (R-3): `dispatching(kind, record)` is recorded
before every POST of the record in this page; a later status read answering typed
`unknown_operation` (`observeUnknown`) starts a confirmation: the page keeps polling,
and the record becomes forgettable only when a second typed-unknown read arrives at
least 5 s after the first (L-5: a single read can precede an admission whose response
the network lost). Forget is therefore offered only after this page's own Retry (or
first dispatch) was followed by two such reads. Forget asks for confirmation, is never offered while the operation is
known and unreleased, and only removes the browser record. Explicit removal rereads identity and confirms absence. This is advisory
coordination, not atomic localStorage locking; the native store serializes effects.

An inspected released preparation history may coexist with candidate launch.
Explicit Open requires completed prepare_reusable with verified receipt and native
prepared status; it calls B3's public `openPrepared` selection action, which fences
older lists/selections/reviews and invokes server `/select`. Candidate Review and
Launch stay explicit. A retained context for another editor project asks the user
to select that project first. A standalone Slow-control UUID never guesses task.

Qualification: `tests/unit/tools/candidate_console/test_new_run.py` owns fresh
policy-before-read, isolated source/manifest/config drift, exact recovery metadata,
HTTP parity and refusal ordering. `tests/browser/new_run.mjs` uses the existing
explicit browser environment and real offline preparation/native candidate worker
with guarded local deterministic provider. It does not qualify real model quality,
training, API access or GPU execution.

## Source-declared native training

The same saved-source New run / retained-capture controllers accept reusable
four-stage declarations. Settings are edited in the tuning inspector or source,
then reviewed and saved; neither NewRunSelection nor launch payloads add overrides.
The source hash binds sparse authored presence. Preparation resolves settings and
seed through native owners; launch invokes the existing native tuner. Old three-stage
source is never automatically upgraded. The inspector labels epoch ceilings and
separate sampling/training seeds, exposes omission/null/value, preserves advanced
rules and disables numeric/checkbox/default/null controls while source is dirty.
Invalid numeric drafts survive node navigation and block Review/Save until repaired
or explicitly replaced by default/null. Read-only rule summaries disclose task
constraints are still runtime-owned. Set `CONSOLE_TRAINING=1` for the four-stage
mode of the existing `tests/browser/new_run.mjs` command.

Offline browser and code witnesses exercise detached operations, native admission,
protocol/staging and terminal output verification with provider, measurement and
tuner effects substituted. They establish transport and artifact integrity, not
real scientific training, historical replay, API access or GPU qualification.

## Configured native chains

`ConsoleConfig.tasks` and `native_chain_choices` default to empty tuples. An empty
configuration supports known-UUID monitoring; a native-only configuration requires
no candidate task or editor. `NativeChainChoice(choice_id, label, request)` uses a
unique task-style ID, a 1–160 character label and the public
`NativeChainOperationRequest` unchanged. Startup checks canonical configured paths,
not capture freshness, pinned contents or destination availability. An explicitly
configured credential file is still validated at startup; after deletion, restart
with `credential_file: null` for monitoring or repair that file.

`NativeChainConsole(console)` provides `choices()`, `review(selection)` and
`launch(selection)`. HTTP GET `/api/native-chain/choices` returns descriptors only.
POST `/api/native-chain/review` accepts `NativeChainChoiceSelection(choice_id)`.
POST `/api/native-chain/launch` accepts `NativeChainLaunchSelection(choice_id,
operation_id, expected_request_digest)` and returns `OperationHandle` with202.
The shared RequestBoundary and threadpool transport apply unchanged.

Review returns choice ID/label, public request digest and `NativeChainAdmission`,
plus request fields capture_path, envelope, read_only, network, devices,
environment_names, timeout_seconds, input_max_bytes, max_iterations_observed and
max_observation_bytes. `credential_readiness` observes required names from admission
and forwarded names from the request through the private-file reader; it neither
reserves admission nor authenticates providers. Admission supplies run/recipe,
workspace/final iteration, capture/input identities and checkout/Git paths. Full
scientific settings, source bytes, checkout commit SHA and routes are not a console
review projection; inspect the original capture for those settings.

Launch first looks up the UUID, before choice/capture/source/credential reads.
An existing native-chain record must match the public request digest; it is
submitted unchanged with empty launch environment. Choice ID/label need not still
exist or match. Corrupt/conflicting records refuse, never become fresh launches.
For absent UUIDs, resolve configured choice, compare digest, call the public native
review owner, check editor separation, read selected credentials and submit the
identical typed request. Operation admission owns concurrent claims and rechecks.
No console runtime, claim, request registry or automatic retry is introduced.

Fresh review/launch refuses pinned input or capture paths writable by configured
authoring projects: source_file, sibling .<source-name>.authoring.lock,
<source-name>.versions.json and recovery
descendants. Writable destination/recovery overlap also refuses. Unrelated sources
in the same project remain editable. Existing-record recovery bypasses this fresh
policy. External edits remain subject to native capture rechecks before dispatch.

`StatusView.kind` includes native_chain and its optional `native_chain` field
projects the public `NativeChainObservation` unchanged. Absent native_chain is
omitted for legacy responses. Receipt-derived fields remain null and
receipt_available false for chains. Current evidence and terminal-time evidence
remain distinct; lifecycle completion is not scientific success. Token reads
use the shared operation accessor and return one whole-chain cumulative snapshot,
including continuations. They validate controls and available identity anchors
without revalidating scientific output payloads; native-only scope/identity metadata
discloses that boundary. Status/log reads
never require configured choices, candidate tasks or editor selection.


### Native browser state and evidence

`native-chain.js` owns one page-memory pending selection and reviewed request
digest; choice generation and session revision fence late responses. Changing
choices invalidates review without erasing unresolved intent. Initial launch
allocates one UUID before POST. Lost responses and reconnect read that UUID;
only explicit Retry resubmits the retained payload. There is no automatic POST or
replacement UUID. Only a confirmed admission enables explicit Review another
native capture to clear the form; this does not stop the existing operation. Reload follows the UUID URL/remembered ID for monitoring only.
No credential or launch payload enters persistent browser storage.

`native-chain-monitor.js` renders the public observation using safe text DOM.
Current evidence and terminal-time evidence are labeled separately. Missing
terminal/checkpoints are unavailable, not zero/success. Mixed/no_records, timeout,
unknown cleanup and invalid evidence retain their own fields. The existing app
poll/cursor/epoch remains the only monitor loop. All supported operation kinds
use the same token table; selecting another UUID clears prior rows/times/provenance,
and epoch checks fence late responses. Native cumulative scope appears in the
status line; identity provenance and scientific/billing limitations are in the
expandable detail. Direct UUID navigation/reconnect needs no choice
or editor fetch; the existing New run task loader is deferred to Workflow or Run entry. Empty candidate choices disable Prepare with explanatory copy.

`tests/browser/native_chain.mjs` uses the explicit Python/Playwright/Chromium and
CONSOLE_EVIDENCE_DIR variables. From a clean committed checkout it creates an
external synthetic task/capture, runs real Chromium/authenticated HTTP/detached
native shell with two pseudo iterations and checks restoration/verified outputs.
It loses an actual launch response, retains/retries one UUID, preserves unrelated
editor drafts, reloads the direct monitor and recovers through code/HTTP after
source/capture removal and monitor-only restart. Separate synthetic projection
cases exercise async fences and mixed/timeout/unknown/invalid evidence. API cost
and scientific GPU execution are zero; hardware observation is read-only. These
checks do not qualify real LLM behavior or scientific training.

## Workflow builder task versions

Authenticated `GET /api/editor/task-choices` returns typed
`{choices: [{choice_id, binding}]}` projected from the same configured
`TaskReferenceTarget` tuple used by authoring. Only choices with `task_revision`
are present. Empty choices preserve ordinary unbound editing. This inert GET
does not inspect files, compose/import tasks or start native observations; internal
resource paths/settings and credentials are absent. Metadata is configured intent,
not verification of current task contents or execution readiness.

The Task package and version panel is always visible and never empty: it states
the saved binding (`This workflow uses task package …, version …`) or that the
workflow is unbound, then either the version selector with Update workflow
references (when choices exist) or `#editor-task-unavailable`, which explains that
no configured task declares `task_revision` and links the README's "Bind a task
version". Refresh task choices is always present.

Workflow builder shows saved binding separately and starts with no task selection.
Users explicitly select a choice (or click the unique matching saved-choice action).
`editor.js` remains the project/draft/generation/conflict/review/Save owner;
`editor-task-controls.js` is a projection-and-callback view without requests or a
second draft. Ordinary bound review uses `task_reference_selection`. Clean explicit
Update uses the existing `task_references` proposal without a second selection.
Dirty Update is disabled and its callback guarded; selection remains available
so matching bound edits can be reviewed/saved before updating.

Task review displays native observation, exact Python diff and ordered
retained/requires_review/blocked findings. Save is unavailable for blocked or
unsupported review and until all findings have an explicit acknowledgement;
current-snapshot adoption has its own confirmation. The existing Save route gets
`task_reference_acceptance` from the reviewed snapshot, never the current dropdown.
Source/selection/base/review/connection changes clear acceptance. Reconnect refreshes
metadata without replacing drafts, retaining a selection only while choice ID and
full binding still match. Changed native identity uses the authoring owner’s
[fresh-candidate and native-profile checks](../workflow_authoring/authoring-contract.md#changed-task-versions-for-fresh-candidates);
`execution_ready` remains false. No existing run/capture is rewritten.
