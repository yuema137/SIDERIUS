# Ordinary-file authoring contract

`WorkflowAuthoring(Project)` owns ordinary-file read/review/save of one configured source.
`AuthoredWorkflowDocument` (v1 or reusable v2), its native catalog and the source bridge own declaration
semantics. Unbound source/document operations never resolve or import referenced files.
Explicit task-reference selection enables the separate bounded inspection below. Recovery copies do
not authorize execution and are never a source revision/publication system.

`Project` selects an explicit normalized absolute project root, source file and
existing 0700 recovery directory. Source/recovery are strict descendants of the
root. Source is current-user-owned, regular, single-link, UTF-8 and at most
32 KiB. Ordinary permission bits (0000–0777) are preserved; special bits refuse.
The current caller must have access sufficient for read/save. Observed symlink
components and unsafe file types refuse. Trusted local directories are required;
malicious same-user swaps are excluded.

Read returns exact text/byte SHA-256, native document or diagnostics, declaration
status and native-catalog-derived binding choices. Unsupported source is viewable
but cannot be overwritten by this API until repaired externally. Review accepts
an expected base SHA-256 plus a discriminated source/document proposal. It reads
and validates the base, renders documents with the existing renderer, refuses
source/rendered output above 32 KiB and returns exact proposed bytes/hash/diff.
Rendering may lose comments and formatting; that change appears in the diff.

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
Binding choices derive from the same catalog for either variant. The browser
renders managed_candidate externals as read-only managed roles; it never creates
a location editor or location key for them. Unsupported preparation options have
no structured editor and remain intact through other edits. Unbound review/save remain
inert declaration operations without explicit task-reference selection;
reusable preparation/launch retain their candidate preparation/operation owners.

## Native training inspector

Source/read and review projections include optional typed `training` presentation
values for reusable four-stage documents. The native settings parser and effective
ingress projection own values; the inspector only names supported presentation
controls. `document.training_settings` remains sparse. Unset removes a key, null
is explicit, and a supplied value remains authored. Numeric blanks block review
without becoming zero/null. Epoch controls are ceilings, independent of parameter
rules and native planning. Sampling and training base seeds have separate controls.
Nested workflow parameter rules are read-only in the inspector and editable in
Source; untouched rules and advanced fields survive edits. Task rules are resolved
later by native owners. All controls participate in the existing source-dirty,
review, save, conflict and generation fences; launch payloads carry no overrides.

## Bound-source publication boundary

Inert read accepts the optional v2 TaskBinding declaration. Bound review and Save
require explicit configured selection and findings acceptance. Unbound legacy
Save retains its inert behavior and wire serialization; omitted new optional
fields remain omitted. Pin removal, changed native identity and unresolved
compatibility refuse publication. Reusable preparation independently enforces the captured pin through its
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
default replacement or scientific compatibility policy exists here. The current source must resolve to an unambiguous configured inspection policy;
arbitrary source paths are never imported. Original-owner observations of both
configured locations are required for relocation, unless the selected policy is
already the current policy. Native identity compares the original semantic
fingerprint and task_data_path_id, not readable package/revision labels. A changed
native identity or unavailable original policy is compatibility_unresolved and
blocked; native facts and text diff do not certify scientific migration safety.

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

The existing HTTP and Python owners consume these fields. The browser does not
yet provide selection/acceptance controls; no bound GUI authoring capability is
claimed. Native preparation enforcement is owned separately by candidate_prepare;
arbitrary task migration remains unsupported.
