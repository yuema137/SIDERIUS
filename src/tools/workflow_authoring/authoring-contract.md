# Ordinary-file authoring contract

`WorkflowAuthoring(Project)` owns ordinary-file read/review/save of one configured source.
`AuthoredWorkflowDocument` (v1 or reusable v2), its native catalog and the source bridge own declaration
semantics. Unbound source/document operations never resolve or import referenced files.
Explicit task-reference selection enables the separate bounded inspection below. Recovery copies do
not authorize execution and are never a source revision/publication system;
named-version history only reads them.

`Project` selects an explicit normalized absolute project root, source file and
existing 0700 recovery directory. Source/recovery are strict descendants of the
root. Source is current-user-owned, regular, single-link, UTF-8 and at most
32 KiB. Ordinary permission bits (0000–0777) are preserved; special bits refuse.
Save refuses a source without the owner-write bit as typed `read_only`
("This file is read-only on disk: <path>") before any recovery copy, record or
source write, so temp + rename never replaces a file its owner protected.
Opening refuses with the reason and the configured path: `not_found`
("Workflow file not found: <path>"), `not_readable` ("Workflow file is not
readable: <path>") and `limit` ("Workflow file is larger than the 32 KiB editor
limit: <path>"). Any other `OSError` is the route's `filesystem` refusal: a read
says the file or its project folder is unavailable on disk and never mentions a
proposal; a Save says "Not saved: the project folder or its recovery copies could
not be written".
The current caller must have access sufficient for read/save. Observed symlink
components and unsafe file types refuse. Trusted local directories are required;
malicious same-user swaps are excluded.

Read returns exact text/byte SHA-256, native document or diagnostics, declaration
status and native-catalog-derived binding choices. Its legacy `binding_options`
preserves its original serialized fields, bound-only membership and authored
argument order for existing consumers;
`port_inventory` separately lists every declared input socket, including omitted
optional protocol arguments. Each inventory entry exposes the catalog contract,
required/bound state, current source, native node input/output contracts, protocol
owner/output mapping and contract-compatible choices. An unbound optional socket
has `source=null`, meaning no wire is authored, not a payload value. Both views
are inert descriptions and do not validate executable readiness. Unsupported
source is viewable but cannot be overwritten by this API until repaired
externally. Review accepts an expected base SHA-256 plus a discriminated
source/document proposal. It reads and validates the base, renders documents
with the existing renderer, refuses source/rendered output above 32 KiB and
returns exact proposed bytes/hash/diff.
Rendering may lose comments and formatting; that change appears in the diff, and
`ReviewView.removed_comments` lists every comment of the current file that the
exact proposed bytes no longer contain (tokenizer `COMMENT` texts, stripped;
repeated texts count separately; a file that does not tokenize falls back to `#`
lines). The value is computed from the bytes Save would write, against the base
the review read, so it also covers a proposal rebuilt on a newer disk version.
The browser's Save step names these comments; it never computes them itself.

Save revalidates its typed request and exact proposal SHA-256. Under the stable
adjacent `.SOURCE.authoring.lock` advisory lock, it captures and validates base
bytes/mode, compares the expected digest, stores exact base and proposal recovery
copies as SHA256.py, rechecks source bytes/mode, and atomically replaces source.
Identical bytes are a no-op after base validation and the final bytes/mode check. Lock acquisition is nonblocking
and reports busy. Existing lock files must be owned single-link 0600 regular
files and are never unlinked. Recovery directory selection cannot alter lock
identity. Recovery copies are owner-only write-once files; preexisting same-hash
copies must match exactly. Recovery failure aborts replacement. Existing durability
helper defaults remain 0600; authoring opts into preserving source mode before
publication. Recovery retention/GC is outside this version.

Serialization is guaranteed only for cooperating clients taking this lock.
An ordinary external write observed before either comparison refuses. A
noncooperating write after final comparison and before replacement may be lost
and absent from recovery. Later read cannot prove that window did not occur.
A → B → A with identical final bytes is an unchanged content base, not edit
history or runtime identity. No force save, automatic merge, source execution,
scientific readiness checks or native launch changes belong to this owner.

Reusable documents round-trip through source/document proposals and read/review
response models without adding a workspace or discarding preparation_options.
Binding choices and complete port inventory derive from the same catalog for
either variant. The browser renders managed_candidate externals as read-only
managed roles; it never creates a location editor or location key for them.
Unsupported preparation options have no structured editor and remain intact
through other edits. Unbound review/save remain inert declaration operations
without explicit task-reference selection;
reusable preparation/launch retain their candidate preparation/operation owners.

## Named versions

`versions.py` owns the version record, a sibling of the source named
`<source name>.versions.json` (for `workflow.py`: `workflow.py.versions.json`),
validated by `VersionRecord` (`schema_id="siderius.workflow-versions/v1"`,
`source_name`, ordered `versions`). Each `RecordedVersion` holds `sha256` of the
exact source bytes, `name`, timezone-aware `recorded_at` and `origin`: `saved` (a
named Save) or `observed` (unnamed base bytes first seen at a later Save: a
pre-record workflow or an external edit). Names are 1-64 characters without
control characters or surrounding whitespace and unique within the record. A new
name (`SaveRequest.version_name`, type `NewVersionName`) additionally refuses any
character of Unicode category Cc, Cf, Cs, Co, Cn, Zl or Zp (zero-width, bidi and
other format controls, separators, private-use and unassigned code points), so two
history rows never look identical; records written before this rule keep loading
through the unchanged `VersionName`. No other naming rule exists. No Git
dependency exists. Names are presentation metadata only: they never enter source
bytes, declaration digests, preparation requests or run identity; the source
SHA-256 remains the version identity, and A → B → A records a third row with A's SHA.

`SaveRequest.version_name` is optional and omitted from serialization when absent;
absent means the next unused `vN`, where N starts at one more than the number of
named Saves. Under the existing source lock and before any recovery copy or source
write, Save reads and validates the record (regular owned single-link file, no
symlink, at most 512 KiB, matching `source_name`, at most 1000 rows), refuses a used
name and prepares the appended record; any such refusal is `version_record` and
writes nothing. The byte cap is sized so 1000 worst-case rows (64 four-byte UTF-8
name characters) always fit, so the row cap is the operative Save limit; either
refusal message names both limits. If the last recorded SHA differs from the base,
an `observed` row precedes the `saved` row. After the source is atomically replaced,
the record is published by temp file + fsync + rename, keeping its permission bits
(a new record takes the source's bits). If that write fails, Save returns the
distinct code `version_record_not_updated` with the saved `current` view: the source
is saved, the old record is intact, and the next Save records these bytes as an
`observed` row. Identical bytes record nothing.
`SaveView.version_name` reports the recorded name.

Without a record, workflows keep working: `GET /versions` lists the current bytes
as one `unrecorded` current row and the first Save creates the record. `versions()`
returns `VersionList` (record path/presence, current SHA, suggested `next_name`,
chronological `VersionEntry` rows with list `index`, `current` and
`bytes_available`). Current bytes that are not the last recorded SHA appear as a
final `unrecorded` row. Version bytes are the existing write-once `SHA256.py`
recovery copies, read only when owned, regular, single-link and hash-equal; no
second byte store exists. `version(index, sha256)` returns `VersionDetail` with
read-only source and a unified diff against the preceding row when both byte sets
are available, otherwise source/diff are null (SHA only). A stale index/SHA pair
is `conflict`. An invalid record blocks history and Save until it is repaired or
moved aside; `recorded_name` (run-preparation display) treats it as unnamed.

## Non-executable binding drafts

`workflows.definition.draft.WorkflowDraft` holds a validated base document and
unique binding patches. An absent patch retains the original binding; a patch
with `source=null` disconnects the socket, never supplies a null scientific
payload. Targets must be existing capability inputs or catalog protocol arguments.
Required disconnections remain inspectable but cannot become a published document;
optional disconnections remove that argument. Promotion uses the existing native
document validator for source contracts, references and acyclicity.

`POST /api/editor/{project_id}/draft` accepts `DraftRequest` and returns the draft
plus its inspection (`incomplete`, `invalid`, or `complete`). It checks the saved
source digest, performs no publication and writes no recovery copy. Only complete
inspection contains a complete declaration document; this does not certify execution
readiness. Each inspection carries `diagnostics` (legacy strings, unchanged) and
`problems`, one typed `DraftProblem` per diagnostic: `code`
(`required_unbound`, `external_binding_required` or `declaration_invalid`),
`node` and `field` (the argument name, or `request` for an external request) when
the problem belongs to one socket, and `message`. For socket problems `message`
equals the legacy string; a native validator refusal keeps one legacy string
(the whole `ValidationError`) and yields one `declaration_invalid` problem per
validator error, located only by its dotted validator path in `field`. The editor
lists `problems` and never derives one itself. The normal review route
also accepts `DraftProposal(kind="draft")` and promotes it before the existing
source review, task acceptance and Save boundary. Neither draft route changes
preparation or launch admission. A stale base refuses and leaves the caller's draft
intact. Drafts are not persisted by this API. `base_document` is any validated
document, not necessarily the saved one: only `expected_sha256` binds the saved
source. The console's unified draft relies on this to review layout and inspector
edits together with binding patches in one `DraftProposal`.

## Node add/remove proposals and catalog projection

`GET /api/editor/node-catalog` returns `NodeCatalog` (`options.node_catalog`), a
read-only projection of the native catalog: one `CatalogEntry` per capability per
protocol whose output is that capability's input (with owner and ordered
`CatalogArgument` name/contract/required), plus one external-request route
(`protocol=null`) per capability. The browser palette lists only these entries.
Each `CatalogArgument.produced_by` names the capabilities whose output carries its
contract (empty: an external input). `NodeCatalog.guide` (`CatalogGuide`, owner
`capability_guide.py`) carries palette guidance derived only from `CAPABILITIES` and
`PROTOCOLS`: per capability (`CapabilityGuide`) its stable topological `stage`,
`connects_from`/`connects_to` (a -> b when some protocol producing b's input reads a's
output), and a one-line `description` from `CAPABILITY_DESCRIPTIONS`, the single
owner of that presentation text (no prompt or execution path reads it); plus
`context` (capabilities without an upstream capability that feed one: currently
interpretation, literature) and `chain` (the remaining stage order, the suggested
build order: proposal, implementation, validation, tuning). A capability missing a
description fails the catalog route; `tests/unit/tools/test_workflow_node_edits.py`
binds the table and edges to the catalog.

`AddNodeProposal(kind="add_node", source, node, capability, protocol, binding,
arguments, x, y)` and `RemoveNodeProposal(kind="remove_node", source, nodes)` are
`ReviewRequest` proposals applied to the exact proposal source (like
`LoopProposal`, so a previously reviewed unsaved source can carry them), but as
targeted byte edits (`workflows.definition.source_edits`), not canonical
re-rendering: comments and every unaffected byte survive. The request schema
refuses (422 `validation`) a capability outside `CAPABILITIES`, a protocol that does
not produce the capability's input, a binding on a protocol route, arguments on an
external route, and unknown or duplicate sockets. Review then refuses with 409:
`node_edit` (duplicate node id, unknown node, non-literal source shape),
`draft_incomplete` (one diagnostic line per unbound required input),
`draft_invalid` (a bound source the catalog projection does not offer for that
socket), or `node_dependants`. The edited source then passes the ordinary
`reviewed_source` parse/validation, task-reference and Save boundary; a successful
review adds `node_edit: NodeEditSummary` (`added`, `removed`, `disconnected` input
connections of removed nodes, and a `message`). The diff remains the authority.

Removal deletes each node, its own request bindings and its layout position.
It refuses (`node_dependants`, nothing written) when a remaining node reads a
removed result through any argument, when the research-loop feedback names a removed
node, or when no capability would remain; it never rewires or disconnects other
nodes implicitly. Removing a dependent chain together is allowed. The edited source
is then re-parsed and validated before it is returned: a removal that leaves another
reference dangling (a route source or target, a `SelectedSource` merge candidate, an
adaptor input) is refused as `node_dependants` with the validator's diagnostics
("Cannot remove <ids>: ..."), never returned as source. Those consumers are not yet
named individually like ResultSource readers are. The browser editor no
longer sends `remove_node`: it deletes through `NodeDraftsProposal.removed` (below),
where deletion always succeeds as a draft and these cases become located problems.

A node with unbound required inputs is a draft-only state. `POST
/api/editor/{project_id}/node-draft` accepts `NodeDraftRequest(expected_sha256,
proposal)` and returns `NodeDraftView(proposal, status, diagnostics, ports)`:
`incomplete`/`invalid`/`complete` with the same messages Review would give, and
`ports` in the ordinary `PortInventoryEntry` shape (choices are the base
document's contract-matching externals and node results). It checks the saved
digest, renders nothing for publication and writes no recovery copy; a stale base
is a conflict. Only a complete add can be reviewed, so a saved document is always
valid. Constructor imports added by an insertion are kept by a later removal.

### Multi-node drafts and new external inputs

The browser editor uses `NodeDraftsProposal(kind="node_drafts", source, nodes,
externals, document=None, bindings=(), removed=())` (`models.py`, applied by
`node_edits.apply_node_drafts`) for any number of pending additions in one review.
`nodes` are `PendingNode` values (the `AddNodeProposal` fields without `kind` and
`source`; `AddNodeProposal` subclasses it). `externals` are new
`ExternalBinding(id, contract, location)` or `ManagedCandidateBinding(id, contract)`
values that pending nodes and saved sockets may read. Pending nodes may read each
other's results, new externals and saved results. The schema requires at least one
node or external and unique new ids. Review refuses with 409 `node_edit` (an id
already in the base document, or a source shape `insert_external`/`insert_node`
cannot edit), `draft_incomplete` (every unbound required input of every pending
node), or `draft_invalid` (a pending binding the projected choices do not offer, or
a combined document the validator refuses).

When `document` is null and `bindings` is empty, the result is a set of targeted
insertions: `source_edits.insert_external` appends each new external to the literal
`externals` tuple, then `insert_node` appends each node and its position. Every
anchor byte, including comments, is kept and the result is re-parsed. A `document`
(edits of saved content: moves, inspector, loop) or `bindings` (`BindingPatch` on
saved sockets, which may read pending results) renders the combined document
canonically through `inspect_draft` and `render_workflow_source`, exactly like a
`DocumentProposal`/`DraftProposal`. So only a draft whose saved content is unedited
keeps author comments. The browser omits `document` when it equals the anchor, and
moving only pending cards does not edit saved positions.

`POST /api/editor/{project_id}/nodes-draft` accepts `NodeDraftsRequest(expected_sha256,
proposal)` and returns `NodeDraftsView(status, diagnostics, problems, ports)`. It
checks the saved digest and writes nothing. `ports` cover every projected node:
saved sockets show the `document` (or anchor) source *without* `bindings`, which the
browser projects. Their choices, and those of pending sockets, include pending
results and new externals of the matching contract (`binding_projection(...,
choices_from=)` over an unvalidated `model_construct` projection used only for
choices). `problems` locate each unbound input (`DraftProblem` node and field).
Saved documents stay valid because only a `complete` draft can be reviewed.

`GET /api/editor/external-inputs` returns `ExternalInputCatalog`
(`external_inputs.external_input_catalog`): one `ExternalInputKind(contract,
managed, summary, example)` per catalog contract that no capability produces as
a result. `managed` derives from `ManagedCandidateBinding.contract`, minus
`literature.input` (which also needs `literature_settings`). It applies only to
reusable (schema 2) documents; a managed binding in a schema 1 document is
`invalid`. `summary` is one plain sentence and `example` is a placeholder file name.
No location is ever proposed. Task packages declare none of these inputs, so the
author types a project-relative path to a JSON file holding the contract's
`native_type` value. The path is read only when a run is prepared.

## Native training inspector

Source/read and review projections include optional typed `training` presentation
values for reusable four-stage documents. The native settings parser and effective
ingress projection own values; the inspector only names supported presentation
controls. `document.training_settings` remains sparse. Unset removes a key, null
is explicit, and a supplied value remains authored. Numeric blanks block review
without becoming zero/null. Epoch controls are ceilings, independent of parameter
rules and native planning. There is no seed control: the retired `sampling_seed` /
`train_base_seed` pins are refused, and the run seed is chosen at launch.
Each `TrainingControl.help` (`TrainingControlHelp`) projects the field's entry in
`CandidateTrainingSettings.model_json_schema()` for `WorkflowLaunchConfig`:
`description`, `unit`, `minimum`/`maximum`, `exclusive_minimum`/`exclusive_maximum`
(read from the field or its nullable `anyOf` branch) and `schema_default` (the
launch-config field default). `has_schema_default` is true only when the schema
declares a `default` key, so a declared `null` default (shown as "Schema default:
null") is distinct from an absent default (no default line). Other keys the schema
does not declare stay `null` and are not shown.
`effective` remains the resolved native value for the document.
`TrainingInspector.policy` (`TrainingChoiceControl`, `policy_controls`) projects the two
required launch choices training admission has no default for: **Health checks**
(`healthgate_mode`: Record only = `observe_only`, Block on failure = `blocking`) and
**Result standing** (`result_authority`: Diagnostic = `diagnostic`, Scientific =
`scientific`), each with a one-line plain explanation. Option values come from the
native `HealthGateMode`/`ResultAuthority` Literals; `value` is the authored key or
`null` when unset or not a native value. The browser renders them as
`#editor-training-policy` above the training settings: choosing writes the authored
key, "Choose…" removes it, and an unset choice is marked on the field ("Required:
choose one. A run cannot start without it."). Save stays allowed; the console's
preparation review refuses the run with the launch-policy owner's message.
Nested workflow parameter rules are read-only in the inspector and editable in
Source; untouched rules and advanced fields survive edits. Task rules are resolved
later by native owners. All controls participate in the existing source-dirty,
review, save, conflict and generation fences; launch payloads carry no overrides.

## Research-loop editing

`AuthoredLoop` on the declaration remains the only loop authority. Source/read and
review projections include optional `loop_template`: the one supported
tuning→interpretation feedback (`protocol="tuning-to-interpretation"`,
`history="native-research/v1"`, `final_iteration=1`) when the graph has exactly one
tuning and one interpretation node; otherwise it is absent and feedback stays
source-authored. The template is inert until reviewed and saved.

`ReviewRequest` accepts `LoopProposal(kind="loop", source, loop)`: the exact
complete proposal source is parsed, only `definition.loop` is replaced (`null`
removes it), and the result is rendered through the normal canonical renderer,
which revalidates endpoints and `final_iteration > 0` (strict integer). It then
follows the ordinary review, task acceptance and Save boundary. Parsing source
rather than a browser JSON document keeps other authored values exact (browser
JSON turns `2.0` into `2`), so add-then-remove on a canonical source restores its
original bytes and declaration digest, and unchanged loop proposals publish no
bytes. A declaration without a loop renders and digests exactly as before.
Endpoint rewiring and loop execution admission (interpretation profile, native
loop owner) remain outside the editor.

Byte preservation holds only for an already-canonical source (one the canonical
renderer produced). Review re-renders the whole declaration, so a hand-formatted or
commented source is rewritten into canonical form by its first reviewed loop edit;
the diff shows that rewrite before Save.

Stop conditions travel inside the same `LoopProposal.loop` as
`AuthoredLoop.stop_conditions`; the editor adds no separate proposal, model or
validator. The declaration stays authoritative: request parsing refuses a
`metric_threshold` without a non-empty `metric_id` or with a non-finite/non-number
`threshold`, a non-integer or non-positive `no_improvement.completed_bodies`, and
a `judge` (`JudgeStop`) without its `criterion` or with a non-positive
`min_completed_bodies` (all 422 `validation`); the declaration refuses more than one
condition per kind, `completed_bodies >= final_iteration` and a judge
`min_completed_bodies >= final_iteration` (422
`source` diagnostics with `field_path`, messages never forwarded). Refusals write
nothing. An empty tuple is omitted from source with its unused constructors, so a
condition-free loop keeps its bytes and add-then-remove restores them. The editor
does not know the task's declared metric: `metric_id` is a validated text field,
and a mismatch with the run metric fails the loop at execution (the worker
contract), not at Review.

## Workflow templates and advice targets

Owner: `templates.py` (the only template catalog) and `advice_targets.py`.
Routes (`tools/candidate_console/template_routes.py`, authenticated):
`GET /api/editor/templates` -> `TemplateCatalog` (`id`, `title`, one-line
`description`, `preview` = nodes with capability/position, result edges, loop
endpoints and `final_iteration`, all derived from the template document);
`POST /api/editor/{project_id}/template` with `TemplateImportRequest`
(`template_id`, `expected_sha256`) -> `TemplateImportView` (`template_id`,
unsaved `source`); `GET /api/editor/advice-targets` -> `AdviceTargets`.

Templates are reusable v2 shapes with no task, data, advice, output-type or
training values except the launch policy pair, which training admission requires
and has no default for: `training_settings={"launch": DECLARED_LAUNCH_POLICY}` =
`healthgate_mode="observe_only"`, `result_authority="diagnostic"` (record-only Health
checks, diagnostic standing, the pair in `examples/workflow_declarations/
reusable_training.py`). It is written visibly in the rendered source, claims no
scientific standing and is editable in the Train & tune inspector; all other launch
values stay native defaults:

| id | Shape | Profile |
| --- | --- | --- |
| `single-research-loop` | interpret -> propose -> implement -> validate -> train, feedback train -> interpret, `final_iteration=1` | `native-interpretation-candidate/v1` |
| `single-loop-with-advice` | same, proposal `human_advice` -> managed `advice`, `expert_context` -> managed `findings` | same |
| `single-step` | propose -> implement -> validate -> train, no loop | plain candidate |

Every external is a `ManagedCandidateBinding` routed as `check_candidate_roles`
admits. Import is write-free: it reads the current source, refuses a stale
`expected_sha256` (409 `conflict`) or an unparsed source (409 `unsupported`),
copies the project's own task references (v1: `manifest`/`data_root`; v2: the
references and accepted `task_binding`) and renders canonical source. The
browser reviews it as an ordinary `source` proposal; a bound source therefore
still requires explicit task selection, and only Save publishes. No template
contains Literature: no catalogued protocol joins `literature.output` into an
interpretation-fed proposal, and N reviews -> one proposal needs the B6
aggregation work (B6-1/B6-3/B6-4).

Advice targets name where each agent reads free-text advice:
`preparation_options.proposal_advice` / `implementation_advice` /
`validation_advice` and `training_settings.launch.human_advice_tune`
(tuning). `advice_targets()` fails closed if a field leaves its owning model.
The proposal target carries `socket` (`interpretation-to-proposal`,
`human_advice`): under that protocol the proposal agent reads the advice only
through the bound socket. No loop-wide advice field exists
(`human_advice_mindset` is an inactive launch field), so advice is per agent.
Unit owner: `tests/unit/tools/candidate_console/test_templates.py`.

## Bound-source publication boundary

Inert read accepts the optional v2 TaskBinding declaration. Bound review and Save
require explicit configured selection and findings acceptance. Unbound legacy
Save retains its inert behavior and wire serialization; omitted new optional
fields remain omitted. Pin removal and unresolved compatibility refuse publication. Changed identities
use the bounded [fresh candidate checks](#changed-task-versions-for-fresh-candidates).
Reusable preparation independently enforces the captured pin through its
[native owner](../candidate_prepare/candidate-prepare-contract.md#accepted-task-binding-enforcement);
successful Save is not preparation or launch approval. Existing runs keep their captured original pins.

## Explicit task-reference inspection/review

`WorkflowAuthoring(project, task_targets=...)` accepts typed `TaskReferenceTarget`
projections of trusted configured choices. Code callers supply the same policy.
The console projects only TaskChoice entries with explicit task_revision; no
independent registry is introduced. Targets own configured manifest/data/config,
read-only source roots, existing inspection parent and bounded check settings.
The browser supplies no target path, factory, mount, environment or device policy.

`ReviewRequest.proposal` additionally accepts `TaskReferenceUpdateProposal`
(`kind="task_references"`, selected_choice_id, expected_task_binding). Selection
alone/read remain inert. This proposal, or a source/document proposal with explicit
`ReviewRequest.task_reference_selection`, reads the
configured LLM routing and invokes the existing setup-review composition child,
without network/devices/caller environment or requested dataset/model/training/
scoring/Health execution. See its returned limitations: trusted factories can
read mounted inputs; no hostile-code or entire-import-closure guarantee exists.

The existing POST `/api/editor/{project_id}/review` and Python service are actual
consumers. Reusable v2 source is required. Unknown/unversioned choices or client
pins differing from the configured selection refuse before child admission.
`ReviewView.task_reference_update` is absent for ordinary reviews; explicit
reviews return the original native owner summary and typed findings. The native
semantic fingerprint and task_data_path_id must match the configured pin. Changed
contents under the same readable label produce identity_mismatch; inspection or
provider failure remains blocked, never substituted with a default provider.

The proposal updates only selected manifest/data references and the accepted pin;
it preserves nodes, bindings, options, settings and layout. No implicit remapping,
default replacement or scientific compatibility policy exists here. The current
source must resolve to an unambiguous configured inspection policy;
arbitrary source paths are never imported. Original-owner observations of both
configured locations are required for relocation, unless the selected policy is
already the current policy. Native identity compares the original semantic
fingerprint and task_data_path_id, not readable package/revision labels. An
unavailable original policy is compatibility_unresolved and blocked. Changed
native identities use the bounded checks below; native facts and text diff do not
certify scientific equivalence.

An unbound v2 may explicitly adopt the currently observed snapshot while retaining
its managed graph, externals, preparation options and training settings. Findings
mark this current_snapshot_adoption; it asserts no historical identity. Bound
source/code/document edits with unchanged accepted native identity return an
authored_changes finding for review of exact authored choices. Both can report
save_supported=true; execution_ready remains false. Unsupported paths preserve
the draft and canonical file. Explicit review writes only fresh inspection scratch;
source bytes changing during inspection return conflict with current bytes and
inspectable proposal.

`SaveRequest.task_reference_acceptance` carries the exact configured selection,
ordered `(code, reference)` acknowledgements for every reconstructed finding, and
explicit `adopt_current_snapshot` intent when applicable. Save revalidates the
source/proposal fences and reconstructs the review under its existing lock after
recovery copies and before publication. Native inspection is repeated even for
identical bytes. Any changed policy, observation, required finding or adoption
intent refuses with a retained inspectable proposal. One shared final source
bytes/mode comparison follows inspection for both no-op and replacement paths,
so an external edit during a slow no-op check cannot report stale success. The
existing atomic writer, recovery semantics and final noncooperating-writer window
remain authoritative; no review-token registry or parallel writer exists.

The existing HTTP, Python and Workflow builder consumers use these fields.
The browser requires an explicit configured selection for ordinary bound review;
its separate Update action submits a task-reference proposal from the saved base.
Update is disabled while source, inspector or reviewed reference edits are unsaved.
The editor retains those drafts and lets the user select the matching configured
choice to review/save first. Selection alone never changes source or adopts a pin.
Every task finding, including retained findings, is displayed in original order;
Save requires explicit acceptance and separate current-snapshot adoption intent
where applicable. The acceptance uses the reviewed selection/findings snapshot.
Changing source, selection, base or connection invalidates that acceptance.
Native preparation enforcement is owned separately by candidate_prepare;
arbitrary task migration remains unsupported.


## Changed task versions for fresh candidates

An already-bound reusable v2 Propose → Implement → Validate graph may switch to
another configured checked identity. Supported forms are the fixed candidate and
the existing native-proposal-fanout/v1 and native-proposal-families/v1 profiles. Both versions must remain separately
available, each matching its own configured native fingerprint and data-path ID.
The previous locations and full saved binding must identify exactly one choice.
Review and Save independently rerun the existing composition child for both;
source or target drift blocks publication. No archive or alternate identity exists.

This slice requires managed generated proposal/storage bindings only, no literal
context/model/checkpoint. Existing native four-stage training may retain its
unchanged source-owned settings when the task changes; both versions still pass
their own identity/interface checks, while only the target receives additional
training-configuration checks for a fresh run. Training settings, preparation
options and graph remain authored as saved. Training workflows combined with an
execution profile remain unsupported. Native candidate role validation owns the
fixed shape; execution_families owns admitted profile lineage. The existing
graph_proposal_bindings and graph_storage_bindings owners reject shared aliases
across proposal or implementation owners. Execution profile, nodes, bindings,
positions, preparation options, training settings and advice must be unchanged;
save ordinary edits first. The target pure candidate check uses existing owners to
resolve the default complete data scope, validate declared allowed output forms
and parameter-rule ownership, and build the native task composition reference.
For retained training settings, the native check also validates actual scope,
formal posture, Health declaration/materialization, authored ordering and
workflow-rule ownership. A non-null managed training data root is refused because
review has no physical run-root binding. No model, dataset samples, actual Health
evaluation, training, provider calls or invented run settings are involved;
execution readiness remains false. Optional candidate request/result fields are
omitted for legacy and unchanged-identity observations. Profile tasks share one
task reference and source-global preparation options, so the pure task check runs
once per old/target task; family and alias ownership are separately checked for
every source instance. No per-instance advice/options interface exists.
Later native preparation independently verifies every proposal seed's target pin,
shared output/advice options and own storage, and every branch storage record.
Family receipt proposal_path=null and fixed/fanout proposal.json semantics stay
with the existing preparation owner; no first-family scalar fallback is introduced.

The native normalized structured Model-I/O, supervision target, custom-loss
applicability and segmentation applicability must match. Missing structured I/O
or unresolved mappings block; prose is never parsed into a shape rule. Changes to
data declarations, metrics, objectives, rules, plugins and narrative guidance are
ordered findings requiring explicit review, along with retained authored advice.
These checks determine supported structural compatibility, not scientific
suitability. The browser displays full declaration details in a collapsed panel.
Save still requires exact ordered acknowledgements and never prepares or launches.
A later preparation builds a fresh target proposal under a new run UUID; previous
captured source, inputs, run history and resume bindings stay unchanged. A fresh
candidate may use a changed target objective after explicit review when the
structured interfaces remain supported. Migrating a trained model or objective
state, combining execution profiles with training, and I/O adaptation remain
outside this slice.

### Draft deletion (`NodeDraftsProposal.removed`)

`removed` lists anchor node ids deleted in the draft (unique; an unknown id is
`node_edit`; a draft must add or delete at least one node or input). Choices never
offer a deleted node's result. Every remaining socket that reads a deleted result is
disconnected unless the proposal patches it explicitly (`bindings` win), so a required
reader reports `required_unbound` (node, field). Deleting a research-loop feedback
endpoint adds `DraftProblem(code="loop_feedback_missing")` and deleting every node with
no pending addition adds `DraftProblem(code="workflow_empty")` (both without node).
Inspection reports these as `incomplete` with `problems`; Review refuses
`draft_incomplete` until none remain, so a saved document is always valid. Without
reader patches, `document` edits or problems, deletions are targeted byte removals
(`source_edits.remove_nodes`) followed by the targeted insertions; otherwise the
combined document (patched, then without the deleted nodes and positions) is validated
and rendered canonically. `NodeEditSummary.removed` lists the deleted ids. Tests:
`tests/unit/tools/test_workflow_node_drafts.py`.
