# P0 implementation handoff

Status: `p0-docs-v2` DESIGN FROZEN; fresh implementation session initialized.
Current checkpoint: C1 implemented, checked (24 passed, 2.57s) and reviewed; C2 next.
This is not an implementation-complete or merge-ready handoff.
Updated 2026-09-10.

## Implementation continuation — 2026-09-10

The operator opened this fresh session to execute C1 -> C2 -> C3.
Publication authorization was subsequently clarified explicitly: commit, push
the scoped branch and open/update the PR autonomously; merge is not authorized.
The earlier local-only endpoint is superseded by `p0-docs-v2` in the primary
design. Preserve the startup evidence below; this amendment does not restart work.
Read CLAUDE in full, this handoff, the full English design, overall.md and
SIDERIUS-Paper `iclr/infra-exp-plan.md` Phase 0 and §21 P0 INFRA/EXP sections.
Read all six pinned v0.1.2 resources in full through the manual route; no
matching installed skill or enabled standards/hooks was found. Web retrieval
returned cache misses and sandbox curl could not resolve DNS; approved read-only
curl retrieved the pinned raw files. No read is represented by a summary.

Git confirms branch/base/current HEAD `docs/organizing-cleanup-plan` /
`2091acdfcb24eb9c8d3953ee7ba1e3ba99926aa0`; local master and origin/master
match. PR #422 merge is in history; its tree equals pin `66d3edf2`.
All four recovery fingerprints below matched before edits. Preserve those
planning edits. Exp remains clean at `ae12ae13abb6e2c1618f0f185ba468d669868399`
on `recovery/persist-demo-run-records`, not master.

Approved scope/invariants: the primary design's C1 navigation, C2 bounded prose
corrections, C3 existing-entry checks; preserve source/config/test behavior,
task science, data, evidence, pins and public paths. No source relocation.
Budget: CPU-only, <=60 seconds per diagnostic subprocess, <=10 minutes total
check execution; no environment rebuild, GPU, metered LLM or campaigns.
Infra `uv sync --group dev --frozen --offline --dry-run` reported no changes;
the actual frozen offline sync audited 95 packages without rebuilding.
Process view contains only this session and its diagnostic; host campaigns are
not visible/audited and none were launched or stopped.

Next: commit the reviewed C1 documentation checkpoint, then implement C2
and C3. C1 link/source audit passed 235 relative links, 20 roots and six classes. Update this continuation at each milestone, commit coherent changes,
push and open/update the PR, repair in-scope validation failures and continue
to PR READY FOR OPERATOR REVIEW with exact-candidate evidence (approved local
CI fallback if remote billing prevents CI). Do not merge or enable auto-merge.
No G0. Commits and PR operations do not need per-operation operator approval.

The planning history and original kickoff below are retained as provenance;
their awaiting-session statements describe the preceding planning checkpoint.

## Identity and authority

- Project / PR: P0 inventory/navigation/minimal existing-entry readiness; no
  GitHub PR assigned for this new work.
- Primary design and live ledger: [step-01-user-map.md](step-01-user-map.md).
- Parent: [overall.md](overall.md); constraints from the Paper plan's P0
  sections, not G0 or the main experiments.
- Canonical repository: `/home/yuema137/SIDERIUS`.
- Branch: `docs/organizing-cleanup-plan`; base and current HEAD: `2091acdf`.
- Working tree: modified `CLAUDE.md` (planning location and reading-mirror
  conventions), four untracked Markdown files in this effort directory.
  No runtime/test/config edits.
  The exact content fingerprints are recorded below after validation.
- Exp read-only counterpart: `/home/yuema137/siderius-exp-current`,
  `recovery/persist-demo-run-records` at `ae12ae1`; clean when checked.
  Framework pin `66d3edf2` has the same tracked tree as infra master.
- Runtime: all diagnostics launched in this planning turn have finished; no
  GPU/LLM/training job launched or stopped. Existing campaigns were not audited.

## Completed work

The primary plan records the 19 visible tracked roots, six public node classes,
current deterministic authorities, exp task/experiment/evidence locations,
confirmed stale documentation and already-open issues #423/#424. It also records
40 passing checks, six workspace-isolated manifest compositions and one TIDMAD
external dry-run. No scientific-lifecycle claim follows from these checks.

2026-09-10 operator-reading addition: added
[step-01-user-map_zh.md](step-01-user-map_zh.md), using the requested DongbeiGPT
explanation style. English remains the sole implementation authority; the mirror
adds no scope, approval or completion claim. CLAUDE now requires synchronized
same-name `_zh.md` mirrors for new or updated active step documents.

Validation of this documentation-only addition: English source fingerprint
matches the mirror, all three command blocks are identical, all 28 checkbox
states match in order, and relative links and whitespace checks pass. Semantic
review preserved scope, acceptance, evidence limitations and publication
boundaries. The existing docs/rule/hygiene command recorded in the English plan
passed 24 tests in 2.60 seconds (exit 0, own venv, CPU-only; bytecode and pytest
cache writes disabled). No runtime, exp, pin or scientific parameter changed.

2026-09-10 scope clarification: operator emphasized a clean tree-shaped
organization while preserving existing module functionality, not codebase
refactoring. Added the structural objective and relocation/validation boundary
to the English plan and synchronized its Chinese mirror and parent overview.
The next layout proposal must distinguish conceptual navigation from physical
paths and identify affected callers before any source move. No source layout
was selected, no module moved, and no implementation checkbox advanced.
Mirror fingerprint, command/checkbox parity, all plan links, whitespace and
`git diff --check` passed after this amendment. No new runtime tests were run;
the 24-test result above belongs to the preceding documentation change.

2026-09-10 continuation checkpoint: added a concrete five-group navigation
tree and before/after disposition table to the primary plan and Chinese mirror.
All 20 tracked directory roots (19 visible plus `.github`) occur in the tree;
the four fenced blocks and 28 checkbox states match across languages. Source
fingerprint, all plan links/whitespace and `git diff --check` pass. No unit,
GPU, LLM or scientific lifecycle run was repeated for this planning addition.

Relocation impact was verified from `pyproject.toml`, sandbox child-script
resolution and external TIDMAD/SuperNEMO callers. A blanket `src/siderius/`
move is not cosmetic and is not selected. C1/C2/C3 retain their docs-only scope;
physical root consolidation remains explicitly unperformed. Search mistakes
and their resolved real paths are recorded in the primary plan.

The pinned upstream working rules explicitly require a fresh implementation
session. This planning context has not been relabeled as one. Operator approval
to continue P0 is recorded, but the new tree is a recommendation, not a source
move authorization. No implementation, commit, push or PR creation occurred.

2026-09-10 freeze and kickoff: after confirming that v0.1.2 explicitly permits
one combined step/PR document and filing upstream onboarding issue #25, the
operator again authorized continuation. Recorded `p0-docs-v1` DESIGN FROZEN for
the already-described local C1/C2/C3 documentation slice. No source-move,
publication or merge approval is inferred. Corrected current parent/step status
without rewriting the earlier planning history. Added all six pinned required
entry/routing/prompt links, not only the three long prompts.

Validation: English/mirror identities, four fenced blocks, 28 checkbox states,
six upstream link destinations, local links and whitespace match/pass. The
existing docs/rule/hygiene command passed 24 tests in 2.65 seconds (own infra
venv, CPU-only, exit 0). `git diff --check` passed. No implementation file,
exp pin, runtime, data or campaign changed; these are planning/docs checks.

## Fresh-session kickoff

2026-09-10 operator amendment: `p0-docs-v2` removes the agent-imposed local-only
endpoint. Commit/push/PR operations are explicitly authorized; merge is not.
The implementation session's initialization evidence above is preserved.
The incorrect endpoint and propagation into handoff were reported as a second,
distinct failure mode in [upstream issue #25](https://github.com/yuema137/structured-coding/issues/25#issuecomment-5624685515):
rules had been supplied, but were applied incorrectly. Read receipts alone do
not establish correct contract interpretation. English/mirror source identity,
fenced-block/checkbox parity and whitespace checks passed for this amendment;
no runtime test or implementation change is claimed by this planning update.

Paste this in a new implementation session rooted at `/home/yuema137/SIDERIUS`:

```text
Execute the single P0 documentation PR, design revision p0-docs-v2.
Read CLAUDE.md first, then this effort's handoff and the full authoritative design:
.structured-coding/plans/infra-exp-p0/step-01-user-map.md
Read overall.md in the same directory and the Paper plan's P0 sections.
Use structured-coding v0.1.2: follow the six pinned entry/workflow/adaptation/
prompt links in the design, reading applicable resources fully, not summaries.
This is one combined step/PR document; do not create a duplicate PR design.
Verify Git/base, preserve the current planning edits, and initialize this handoff
for the implementation session before editing user documentation.
Implement C1 -> C2 -> C3 with small-step validation and logic review.
Keep the English ledger and its _zh.md reading mirror synchronized.
Do not relocate source, change behavior or scientific settings, or launch campaigns.
Commit coherent changes, push the scoped branch and open/update the PR.
Continue in-scope validation/repair to PR READY FOR OPERATOR REVIEW; use the
approved exact-candidate local CI fallback if remote billing prevents CI.
Do not merge, enable auto-merge or push directly to master.
Do not keep asking about already-approved scope or commit/PR operations.
```

This kickoff is a reading route and continuation instruction, not a second
design authority. No read-attestation or enforcement hook was installed.

## Next actions

1. Verify the recorded `p0-docs-v2` freeze and explicit commit/push/PR authority.
   Do not ask to approve the same scope or publication operations again.
   Merge remains separately controlled by the operator.
2. Fresh-session initialization is recorded above; do not start a duplicate
   implementation. Reconcile the amended primary contract and parent, preserving
   the existing six-resource onboarding and startup evidence.
3. Recheck Git/base, both repositories' identities and the existing dirty docs;
   do not discard them or switch to a historical worktree. Initialize this file
   as the implementation continuation record after verifying the freeze.
4. Execute C1 -> C2 -> C3 from the primary plan: inventory/navigation,
   bounded instruction corrections, then minimal entry validation and handoff.
   Reuse the audited commands, respecting each check's stated limitations.
5. Complete authorized commits, branch publication and PR work, inspect the PR
   and exact-candidate validation, then hand off at PR READY FOR OPERATOR REVIEW.
   No merge without explicit approval.

## Boundaries

Use the frozen CPU-only validation contract in the primary design, not an
example Gate budget from upstream. No raw data, secrets, generated artifacts or
scientific parameter changes enter Git. No runtime rewrite, broad migration,
package repair, new capability, G0 or main experiment setup belongs here. If a
minimal entry truly requires a code repair, identify its first cause and amend
the bounded design; stop for material behavior/architecture decisions.

The repository map to be written under `docs/` is user documentation. All
plans and this handoff stay together here. No hook has been installed; fresh
session and compaction recovery are procedural obligations, not enforced hooks.

## Recovery content fingerprints

Current payload SHA-256, excluding this handoff to avoid self-reference.
These identify tested/reviewed content; they do not confer approval. C1 source
base is `2091acdf`; later checkpoint commits are recorded in implementation evidence.

| File | SHA-256 |
| --- | --- |
| `CLAUDE.md` | `6e8d87c33a532e57bc9742fbc519ab83b5221cfb7ca09ea64e81fb90ea8ce081` |
| `README.md` | `1986ae7ddd9e538a138f45d21a9de57ce2d542474839a97160d29f459b86b787` |
| `docs/README.md` | `3e880bd3a3f682db201e04ab714435afe57023e143b55f527267aa8f34f371b9` |
| `docs/agent-reference/README.md` | `5b2ea2b81b2abe2881a26b02bc003e57e0046383a45a9715ae9eda84ada43bd6` |
| `examples/README.md` | `d434eb122298c44a89df23d87184d5b37a33f177b302dfd52e9f63584bb5865b` |
| `docs/repository-map.md` | `3b5f9fd2942a3de6b8428f4cf59f486d4257914eb93cc415a390dedcb53e41cb` |
| `advice/README.md` | `c7924812b8423c78301a0db5a916fc5ae67ce910e10015cd137035c5b25eb958` |
| `ml_models/README.md` | `f7a89e627ffa449da5fa55b364373e403752e22bb2b836bb25158416680ab0e7` |
| `.structured-coding/plans/infra-exp-p0/overall.md` | `4a1d134de3d4bdad61df93476b658b42edb349ad4a5458f55711af0d84c9d7c7` |
| `.structured-coding/plans/infra-exp-p0/step-01-user-map.md` | `40f3dc8cd53fb5f29160eaa3d571ac372a9c77394821e9d56eb4bbc0445b08af` |
| `.structured-coding/plans/infra-exp-p0/step-01-user-map_zh.md` | `536a00ca55b3a570aa2c25f6be148e141e42bf29e710f8aced3012303c51b4c1` |
