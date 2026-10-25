# Ordinary-file authoring contract

`WorkflowAuthoring(Project)` owns inert read/review/save of one configured source.
`AuthoredWorkflowDocument` (v1 or reusable v2), its native catalog and the source bridge own declaration
semantics. Ordinary source/document operations never resolve or import referenced
files. Explicit task-reference review is the separate bounded inspection below. Recovery copies do
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
Identical bytes are a no-op after base validation. Lock acquisition is nonblocking
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
no structured editor and remain intact through other edits. Review/save remain
inert declaration operations for source/document proposals and unbound Save;
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

Inert read/review accepts the optional v2 TaskBinding declaration. Save currently
refuses with `task_binding_unsupported` if either the current or proposed source
is bound, before recovery/publication; identical bound bytes and pin removal also
refuse. Keep the draft for later guarded publication. This is an explicitly
unsupported boundary, not task-identity verification or executable approval.
Unbound legacy Save retains its existing behavior.

## Explicit task-reference inspection/review

`WorkflowAuthoring(project, task_targets=...)` accepts typed `TaskReferenceTarget`
projections of trusted configured choices. Code callers supply the same policy.
The console projects only TaskChoice entries with explicit task_revision; no
independent registry is introduced. Targets own configured manifest/data/config,
read-only source roots, existing inspection parent and bounded check settings.
The browser supplies no target path, factory, mount, environment or device policy.

`ReviewRequest.proposal` additionally accepts `TaskReferenceUpdateProposal`
(`kind="task_references"`, selected_choice_id, expected_task_binding). Selection
alone/read/source review remain inert. Only this explicit proposal reads the
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
default replacement or scientific compatibility policy exists here. A missing
historical owner observation or changed binding is compatibility_unresolved and
blocked; native facts and source diff do not certify scientific compatibility.
Even a verified unchanged pin retains save_unsupported; save_supported and
execution_ready are false. No canonical source/recovery/run is published. Only
fresh local inspection scratch is written. A source change during inspection
returns conflict with current bytes and inspectable proposal; final guarded Save
and native preparation enforcement remain separate unsupported checkpoints.
