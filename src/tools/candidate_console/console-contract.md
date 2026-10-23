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
| GET /api/operations/{UUID}/log | kind=native or operation, offset>=0, max_bytes=1..65536 → LogChunk |

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

The Editor has no Run/Prepare button. Native Prepare still generates its fixed
chain; declaration saves establish neither scientific readiness nor immutable
runtime closure. Source inspection never opens referenced resources.

Qualification: targeted `tests/unit/tools/test_workflow_authoring.py` and
`tests/unit/tools/candidate_console/test_editor.py`; real browser:

```bash
EDITOR_PYTHON="$PWD/.venv/bin/python" \
CONSOLE_PLAYWRIGHT_MODULE=/absolute/installed/playwright \
CONSOLE_BROWSER_EXECUTABLE=/absolute/installed/chromium \
node tests/browser/workflow_editor.mjs
```

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
Theme enum and optional last-operation UUID remain the only persisted values.
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
