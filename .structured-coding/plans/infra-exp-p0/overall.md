# P0 — Existing infra and exp inventory and readiness

Status: P0's bounded C1/C2/C3 documentation design is frozen on 2026-09-10;
implementation is active (C1 complete; C2 next). No source relocation, later development
or scientific experiment is authorized here.
Method: [structured-coding v0.1.2](https://github.com/yuema137/structured-coding/tree/v0.1.2),
adapted to one bounded P0 work package.

## Binding scope

This implements ONLY the first step of SIDERIUS-Paper's
`iclr/infra-exp-plan.md`: P0 / INFRA and its directly related P0 / EXP
inventory. The source plan is authoritative; its HTML is a presentation.
Do not change either to justify a larger cleanup.

The operator explicitly corrected an earlier overbroad proposal on 2026-09-10.
The proposed five-step/seven-PR cleanup, complete scientific migration,
entrypoint reorganization and mandatory six-task two-iteration qualification
are withdrawn from this active plan. Their discovery does not authorize their
implementation. Later infra development and scientific experiments are separate.

Operator clarification, 2026-09-10: P0 should make the existing repository a
clean, understandable hierarchy, preserving module functionality rather than
redesigning the codebase. The detailed plan distinguishes a user-facing
navigation tree from physical directory changes. A nicer diagram alone is not
evidence that the physical layout has changed. Before moving any source, specify
the before/after paths, affected callers and behavior-preserving validation in
the bounded design. No target source layout or source relocation is approved
by this clarification alone; broad refactoring remains excluded.

## Deliverables

1. Inventory of the current six nodes, protocol adapters, execution, scoring,
   resources and recovery, with their actual source locations.
2. Clear current user entrypoints and environment/data/workspace requirements.
3. Classification of outdated, mixed and historical material with concrete
   readers/evidence, not deletion based on names or age.
4. Exp inventory: existing task loaders, baselines, configs, runtime records,
   reports, actual framework pin and explicit data/output locations.
5. Minimal existing-entry checks with exact commands, environment and evidence;
   only repairs that block this P0 outcome may enter implementation scope.

Main-study datasets, treatments, parameter choices, comparisons, ablations and
campaigns are NOT part of infra development. Existing task packages may supply
small regression witnesses when needed; they do not define a new experiment plan.

## Invariants

- Preserve existing runtime behavior, scientific definitions, metrics, Health,
  data splits, budgets, iteration/feedback/resume semantics and provenance.
- Reuse existing modules. No blanket rename, package-layout migration, new
  dispatch/analysis/preprocessing/controller feature or full ownership surgery.
- Do not delete historical evidence or regenerate scientific expected values.
- Keep raw data, credentials and outputs outside Git.
- A docs correction must describe actual source without promoting intended
  capabilities to demonstrated ones.
- If a necessary repair changes behavior or architecture materially, stop with
  exact evidence, options, recommendation and impact for the operator.
- Exp follows any actual P0 interface/path repair, with a bounded paired check.
  An inventory or prose-only change alone does not require a pin bump.

## Current facts

Canonical infra path: `/home/yuema137/SIDERIUS`, based on master
`2091acdfcb24eb9c8d3953ee7ba1e3ba99926aa0`.
The redundant `SIDERIUS-current` checkout was removed recoverably.
The own-venv source is corrected; 35 path-repair tests passed.

Exp inspected at `/home/yuema137/siderius-exp-current`, recovery branch
`ae12ae1`, pin `66d3edf2b2045eaf037fb5cc9ecb3dffee94523b`.
The framework pin and merged master have identical trees.
Recovery branch content must not be presented as exp master content.

Initial read-only audit identified 19 tracked visible infra root directories,
misleading READMEs, historical instructions in CLAUDE, mixed scoring helpers,
old integration data assumptions, and dated diagnostic assets. These are
inventory findings, not authorization for wholesale removal.

## Work organization

[The P0 work plan](step-01-user-map.md) is the single detailed work ledger.
The authoritative planning location is `.structured-coding/plans/infra-exp-p0/`,
following the v0.1.2 default requested by the operator. Keep subsequent PR
details and any handoff in this effort directory; do not keep a second copy
under `docs/plan/`. Project documentation remains in `docs/`.
Use one bounded docs/inventory PR for the mapped work. If minimal startup checks
expose a real blocking repair, specify its exact scope and validation first;
a material repair needs the operator decision above. Do not preallocate later
development PRs here.

The legacy separation ledger records historical work, not this PR's status:
[historical separation record](../../../docs/design/framework_experiment_repository_separation.md).
No new plan or handoff goes at the repository root.

## Acceptance and stop

P0 ends with an evidence-backed map, reproducible environment/entry instructions,
documented exp dependency and data/output authority, and the required minimal
entry checks. A dry-run proves argument construction only; failed, skipped and
unrun checks remain explicit. Fix only confirmed blockers to these outcomes.

Stop at P0 review. Do not begin G0, later infra capabilities or scientific
experiments under this plan.

## Progress

- [x] Canonical infra path repaired and checked.
- [x] Initial current-source and historical-evidence inventory performed.
- [x] Paper high-level boundaries read as constraints, not implementation scope.
- [x] Operator scope correction incorporated; later phases removed.
- [x] Adopted v0.1.2 planning location; preserved the P0-only scope.
- [x] Complete the tracked-root/six-node/exp source audit and baseline entry
  checks (40 focused tests, six isolated compositions, one external launcher
  dry-run); evidence and limitations are in the detailed work plan.
- [ ] Complete the bounded inventory, correct misleading current instructions.
- [ ] Verify minimal existing entrypoints and directly affected exp surfaces.
- [ ] Review P0 evidence and hand off without advancing to later phases.

Current checkpoint: detailed docs-only design `p0-docs-v2` is frozen; its
C1 implementation and review are complete; C2/C3 remain. The baseline checks do not certify real training or
wheel-only execution. Known remaining separation/package exceptions are named
in the detailed plan; they are not silently absorbed into this PR. See
[handoff](handoff.md) for the fresh-session entry and publication boundary.
The operator explicitly authorizes semantic commits, branch push and PR
creation/updates through review readiness. Merge and source relocation remain
outside that authorization; the prior local-only endpoint is superseded.
