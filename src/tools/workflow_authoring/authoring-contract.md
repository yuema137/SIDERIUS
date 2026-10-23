# Ordinary-file authoring contract

`WorkflowAuthoring(Project)` owns inert read/review/save of one configured source.
`AuthoredWorkflowDocument` (v1 or reusable v2), its native catalog and the source bridge own declaration
semantics. Referenced files are never resolved or imported. Recovery copies do
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
inert declaration operations; reusable preparation/launch is not implemented.

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
