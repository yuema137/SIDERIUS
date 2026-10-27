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
`file_status` (`not_needed`, `not_selected`, `readable`, `unavailable`), a `ready`
boolean and bounded repair instructions. No file is read when there are no names
to check. Missing/empty extra declared names also block readiness. Invalid or
removed files after startup remain reviewable with unavailable status; startup
`check` still validates configured credential file shape and permissions.

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
| GET /api/choices | ChoiceView array |
| POST /api/preparations | PrepareSelection → OperationHandle, 202 |
| GET /api/preparations/{UUID}/review | PreparedReview |
| POST /api/candidates | LaunchSelection → OperationHandle, 202 |
| GET /api/operations/{UUID} | StatusView |
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
script/style CSP. Token is memory-only in the browser; IDs may persist. Page uses
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

Slow control: `graph-results-monitor.js` owns `window.renderGraphResults` and the
`#graph-results-observation` section. `app.js` requests the route once per
selected operation inside the existing poll, only for `kind == "candidate"` and
`state == "completed"`; the existing monitor epoch fences replies and selection
clears the section. 404/409 are final for that selection; other failures retry on
the next existing poll. Each body is its own section (`Iteration N` for several
bodies) whose stage label comes from `editorCapabilityPresentation.label("tuning")`
(`TRAIN & TUNE`). No cross-body score or ordering is computed or displayed.

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
completed the loop early; Slow control renders it in plain words ("Research loop
stopped early after body 3 of up to 5: accuracy reached 0.9 (threshold 0.85,
higher is better; best at body 3)", or "… no improvement for 2 bodies …") from
the existing status poll, with recorded values unrounded. The receipt's body
numbers (`attempted_iterations`, `stop_reason.iteration` and its incumbent
iterations) are whole-run indices, so a resumed segment's line says "Body numbers
count the whole run, including earlier segments." The console never
infers per-body progress from an active process. Fixed and non-candidate
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

Slow control: `loop-control.js` owns `window.renderLoopControl` and
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

Slow control shows **Pause at next boundary** beside Stop for an active loop
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
an allowlist ID, never a browser-supplied filesystem path. Slow control presents
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

`/editor.html`, `/editor.js` and `/editor.css` are static assets. The editor shares
the persistent shell and memory-only session with the operation monitor; its
source/review policy remains owned by `editor.js`. `GET /api/editor/projects`
returns configured IDs. `GET /api/editor/{project_id}` returns `SourceView`.
`POST /api/editor/{project_id}/review` validates `ReviewRequest`; `POST
/api/editor/{project_id}/save` validates `SaveRequest`. The existing console
Bearer token, origin, host and 256 KiB wire-body admission apply to every API
route. Browser requests select project IDs and never filesystem destinations.
The [authoring contract](../workflow_authoring/authoring-contract.md) owns source
limits, exact-byte review/save, mode preservation, recovery and race boundaries.
Domain conflicts return bounded current source/diagnostics and, on a stale
Review, the rendered pending proposal/diff. Unsupported-source and parser
failures do not execute selected Python. Unexpected filesystem failures report
an unavailable resource without forwarding exception text.

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
protocols display as adaptor labels inside their actual consumer, not extra nodes.
External source chips remain inspector bindings. Omitted optional ports, argument
creation/deletion and new nodes are not graphical controls in this slice.
Required and bound inputs always render as card rows; optional unbound inputs fold
into one `.circuit-optional` disclosure per card ("N optional inputs"), expandable
and remembered across re-renders of the same graph. While an output is pending,
the summary is highlighted when a folded input is type-compatible.

Canvas view state (zoom, scroll, Arrange view, expanded optional rows) is owned by
`editor-circuit.js`, keyed by project and node IDs, and never reaches a document:
viewing sends no request and cannot change saved bytes. The canvas is a CSS
`transform: scale()` of the world, with positions kept in document pixels
(drags divide screen deltas by the zoom). On opening a graph it fits once
(`editorCircuitGeometry.fitScale`: never above 100 %, never below 40 %, then the
canvas scrolls); the toolbar offers Fit to view, zoom out/in, Actual size and
Arrange view. The canvas grows with its zoomed content up to
`clamp(420px, 100vh - 200px, 860px)`, shows edge shadows toward unseen content,
and a note states how many capabilities are partly outside the view. Arrange view
displays `geometry.place` with no stored positions (display only); a move made
there records the displayed layout as an ordinary local edit and leaves Arrange
view. Overlapping saved cards (`geometry.overlaps`) and unrouteable wires are
reported with that display-only way out.

The workflow-level Research loop panel (`editor-loop-controls.js`, view only;
`editor.js` owns the draft) shows "No research loop declared" with an Add action
enabled only when the server returned `loop_template`, or the declared loop as one
fieldset per facet: Iteration limit (`final_iteration`, whole number ≥ 1; invalid
or empty values stay local and block Review) and Feedback (paper capability labels
from `editorCapabilityPresentation.label`, read-only endpoints). Remove deletes the
loop. Loop-only edits review as `LoopProposal` on the current exact source; with
other inspector edits pending, the whole document proposal carries them. A third
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
binding-draft, conflict and saving fences. Capture review (`ReusableCaptureReview.loop`)
reports the executed request's authored loop, refusing a request loop that differs
from the captured declaration, and the launch summary states "up to N iterations"
or "none (one workflow body)", followed by "stops early when …" for each declared
stop condition.

Socket/drag gestures send no requests. Source editing, disconnection, conflict,
saving and invalid training drafts gate mutations; stale rendered projections
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
Card headings use the paper capability names (`INTERPRET`, `LITERATURE`, `PROPOSE`,
`IMPLEMENT`, `VALIDATE`, `TRAIN & TUNE`) from `editor-capability-presentation.js`;
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
or new-base selection followed by review. A connection failure retains proposal
and reports unconfirmed save. Source/labels/diffs render as text.

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
inputs, the disjoint fully wired interpretation fixture, Arrange view on an
overlapping layout, zoomed drag arithmetic and a non-empty task panel.

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


## Persistent views, routing and session

`index.html` owns a single document with persistent Home, Workflow and Slow control
sections. `navigation.js` owns `/#home`, `/#workflow`, `/#slow-control` and
`/#slow-control/<UUID>`. Empty fragments use Home. Complete UUID validation
precedes operation selection; invalid routes show a local error and suspend
operation polling without mutating a native request. Bare Slow control retains
selection; repeated identical UUIDs do not reset the monitor epoch/log cursor.
Back/Forward and internal links hide inactive sections with `hidden`, update
`aria-current`, and focus the active heading on explicit fragment changes.
Polling/theme changes never focus the document. Controllers and DOM are not
reconstructed. `/editor.html` is only an external compatibility entry: its
external `editor-entry.js` replaces the document with `/#workflow`, with a plain
link fallback and no credential form.

`session.js` exclusively owns the Bearer token in closure memory. It exposes
same-origin API requests and connection/revision notifications, never a token
getter. The single `access-form` captures and immediately clears the password
input. Requests use Authorization, cache no-store and credentials omit; POST
payloads retain their existing owners. No cookie, storage, URL, history payload,
event, cross-tab channel or document-transfer mechanism carries credentials.
Theme enum, optional last-operation UUID and the versioned exact reusable launch
intent are persisted. The launch intent contains only origin/project navigation
context, retained preparation identity, request digest and operation UUID; never
source bytes, native requests or credentials.
Reload/new tab requires Connect again.

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
Editor projects load only on Workflow entry. Choices/project failures remain local;
known-operation reads need neither task choices nor editor configuration. The one
existing visible-document two-second polling loop retains its cursor/epoch owners.

Home's configured-task flow is a secondary disclosure independent of the editor
selection. Prepared workspace, identity, routes, limits, devices/network and
credential blockers remain visible before explicit Launch within that flow.
Workflow references and Advanced → Source start collapsed; successful Review
opens the exact diff. Disclosure toggles do not change edit mode or reviewed bytes.
Unsupported-source status and Inspect source remain visible; conflicts retain
visible summary/actions. A `beforeunload` guard applies only to a real document
exit with pending editor changes. Slow control shows operation identity, native
state, observed time and token quality; facts, token rows and logs are disclosures.
It infers neither scientific success nor complete billing.

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
checks readback. Failure prevents POST. Pending intent is independent of current
project/task/selection, so switching cannot overwrite it. Check/retry is explicit;
reconnect never submits automatically. Completed or eligible initial refused intent
requires explicit dismissal and storage readback confirmation. Monitor uses existing
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
POST `/prepare` returns existing `OperationHandle` with HTTP 202. Both use the
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

`reusable-intents.js` coordinates only the candidate and preparation keys:
`siderius.reusable-candidate.v1` (compatible payload) and
`siderius.reusable-preparation.v1` (version/origin/project/exact NewRunIntent).
Before dispatch/retry/state update/dismissal, stored serialization must equal the
retained record. Readback failure prevents POST. Release evidence is in memory,
requires matching kind/UUID/request digest, and is cleared by storage events.
Completed/operation_failed plus exited process, or confirmed spawn_failed, permits
release; finishing/unknown/alive does not. Only initial live pre-submit refusal
permits refused-intent dismissal. Restored/retried/404/transport outcomes retain
identity. Explicit removal rereads identity and confirms absence. This is advisory
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
authoring projects: source_file, sibling .<source-name>.authoring.lock and recovery
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
or editor fetch; the existing New run task loader is deferred to Workflow entry. Empty candidate choices disable Prepare with explanatory copy.

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
