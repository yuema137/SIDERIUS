# Context Handoff

Canonical template for the PR-scoped Claude Code continuity system.
Copy to `before_end_memory.md` at the start of EVERY new PR and fill it
in for that PR. See `docs/development/claude_context_continuity.md`.

<!-- FIRST_PRINCIPLES_BEGIN -->

## First Principles

These are fixed. The PreCompact guard compares this block against this
template and blocks compaction if it was modified, so improve the wording
here — never only in the live file.

### Evidence before action

- Audit actual code, tests, artifacts, documentation and Git history before
  making a decision.
- Do not infer production semantics from identifiers, filenames or comments.
- Distinguish measured facts, configured policy, task interpretation and
  implementation inference.
- After compaction or resume, verify the handoff against the repository
  before editing.

### Autonomous execution

- Continue autonomously when the correct action is determined by code, tests,
  frozen policy and repository evidence.
- When a problem appears, repeatedly audit and reproduce it before choosing a
  fix.
- Ask the operator only for genuine unresolved policy or authority decisions.
- Do not ask about implementation details that repository evidence can
  resolve.

### Minimal architecture

- Prefer the smallest focused typed boundary.
- Do not perform a large architectural rewrite.
- Do not enlarge giant orchestrator functions when a focused seam exists.
- Do not create duplicate mutable state.
- Isolate unrelated blockers in predecessor hotfixes.

### Task genericity

- Production workflow code must remain task-generic.
- Do not hardcode task scores, models, paths, gate IDs, thresholds, failure
  prose or historical artifacts in generic code.
- Task-specific values belong in task-owned configuration and validation
  fixtures.
- Do not over-optimize for one model, artifact, test or campaign.

### Documentation and evidence

- Update the governing design document and implementation ledger in the same
  semantic checkpoint as the implementation.
- Record actual call paths, files, tests, wall times, mutations, deviations,
  rationale and follow-ups.
- Do not silently deviate from the design.
- Do not claim a property stronger than what tests and artifacts establish.

### Validation discipline

- Every semantic implementation commit must be independently green.
- Prove producer-to-consumer reachability.
- Use mutations where a test could otherwise pass for the wrong reason.
- Decide and run Gate 1 and Gate 2 autonomously when required by the actual
  change.
- Final acceptance requires full CI, then final integrated Gate 2 on the same
  exact SHA.

### Minimum-bounded validation (binding, operator 2026-08-05)

The goal is to PROVE a property, not to run realistically or exhaustively.
Run the minimum bounded workload that yields independent acceptance
evidence.

**Time is the primary cost constraint.** High VRAM is acceptable when it is
safe and correctly attributed; long runtime is NOT acceptable merely because
compute is available. Prefer 25 GB in 5 minutes over a 90-minute run that
economises memory.

Before every nontrivial validation run, record: the exact property proved;
why cheaper evidence is insufficient; the smallest workload that proves it;
expected wall time; a hard wall-clock timeout; maximum rounds, attempts,
epochs and data fraction; explicit early-stop conditions; and what new
evidence each additional case adds.

Cheapest sufficient layer first, never repeating at a costlier layer what a
cheaper one already proved:

    static/schema -> focused unit -> synthetic integration
      -> pseudo/mocked execution -> smallest real LLM or GPU run

**The harness owns the bounds, not the LLM or planner.** Planner output must
never raise the configured maximum data fraction, rounds, epochs or time
budget; the launcher clamps or refuses. Every real run carries an explicit
trial time budget, formal time budget, total wall-clock timeout, bounded
rounds/attempts, and bounded data fraction and epochs. Inner time gates
govern workflow decisions; an OUTER hard timeout guards against any
component running away. Neither substitutes for the other.

Stop as soon as the property is established — unused budget is not a reason
to keep running. Treat an unexpectedly long run as a validation-DESIGN
finding: stop or end at a safe point, audit why the workload escaped its
bound, and correct the harness. Never normalise multi-hour acceptance runs.

Defaults unless the property demands otherwise: Gate 1 at most 1-3 real
calls and 10 minutes; each Gate 2 case at most 30 minutes; the full Gate 2
matrix at most 60 minutes. Exceeding a default requires a written statement
of the distinct evidence gained; if none, shrink the workload. Record
planned versus actual wall time and every deviation.

### Audit before expensive validation (binding, operator 2026-08-05)

Expensive validation is CONFIRMATION, never discovery. Full suites, CI, Gates,
real LLM/GPU/training and long mutation runs may not be used to find wiring,
schema, provenance or harness defects.

Ladder — never skip upward, and each layer must add DISTINCT evidence:

    code/design audit -> static producer/consumer tracing -> focused schema
    and pure-unit tests -> deterministic integration -> production-reachability
    tests -> targeted mutations -> affected subsystem suite -> full local suite
    -> exact-head CI -> minimal real Gate

**Before the full local suite**: state the exact semantic change, the affected
production call paths, and what is explicitly unchanged. Trace every new value
producer -> arguments -> schema -> subprocess/CLI boundary -> record ->
artifact -> real consumer, confirming each hop by source AND execution. Reject
a value that is only a local variable, only printed, emitted into a dict but
undeclared on a schema, persisted but never consumed, or supplied by a test
harness where production does not supply it. Audit EVERY output branch —
healthy, no-records, degraded, skipped, runtime failure, early crash, resume,
diagnostic. Launch facts survive all post-launch branches; result-only facts
are never fabricated where no result exists. Then: targeted tests green, named
mutations caught, pyright on touched modules, ruff clean, full diff reviewed,
design doc synchronized. A surviving mutation is classified (real gap /
equivalent / unreachable / wrong fixture) before proceeding.

**Before CI**: full local suite green from a clean tree, docs complete, no
known work left, and the head is intended to become the frozen head. CI is not
an iterative debugger; do not run it after every small reinforcement commit.

**Before real training or a Gate case**: write a Gate-readiness packet — the
one precise property, what synthetic execution cannot prove, the exact PASS
artifact; proof that the real launch command reaches the path, that every
argument is passed by the real caller, that switches are on, that the verdict
is persisted, and that the harness reads what production writes; a pre-reviewed
bounded candidate when model identity is not itself the property; explicit
wall-time/timeout/round/epoch/data bounds owned by the HARNESS, not the
planner; provenance (SHA, command, candidate source, plan hash, identity,
declarations, device, validity); and a failure-classification scheme decided
in advance.

**During a Gate**: stop as soon as the property is established. Never extend a
deadline mid-run, never rerun until green, preserve every failed attempt. One
bounded rerun only when the first failure is PROVEN a harness or external
transient and the fix does not change the tested SHA. A model collapse or
invalid HealthGate result is legitimate evidence, not a reason to reroll.

**When an expensive run exposes something an audit could have caught**: do not
simply add another prerequisite PR. First explain why the readiness audit
missed it, and strengthen the audit.

### Transport contracts for important fields (binding, operator 2026-08-05)

Every important new field or decision declares its transport contract, in the
governing design document and in the test module that guards it:

    field:              <name>
    producer:           where it is created
    typed boundaries:   every schema it must be declared on
    persistence:        every artifact it must reach
    consumer:           who actually reads it, in production
    failure branches:   healthy / no-records / degraded / crash / resume

The contract is verified by DELETING each hop in turn and confirming at least
one test fails for each. That is stronger than grepping the field name or
checking one schema: it is what distinguishes a delivered value from a value
that merely exists.

None of the following is production-reachability evidence: the field appears
in a log line; a local variable holds it; some function received it as an
argument. Only arrival at the real consumer counts.

### Acceptance identities are read, never reconstructed (operator 2026-08-05)

Never extend a short SHA into a full commit ID by hand, and never infer an
identity from context. Every acceptance identity comes from `git rev-parse`,
the PR API's `headRefOid`, or CI metadata. A fabricated identifier can make a
waiter miss a finished job, or — far worse — claim the wrong head was
validated.

### State the scope of any green claim (operator 2026-08-05)

The project's full CI is unit tests plus static checks BY DESIGN. It does not
promise to run `tests/integration/`, and pre-existing failures there are not a
default merge blocker. "Full CI green" is a correct and sufficient claim.

What is still required: name the scope, and run the targeted integration or
pseudo tests a given acceptance actually depends on.

    full CI green
    + the PR's own targeted integration/pseudo acceptance green

Do NOT expand a PR into cleaning unrelated integration failures. DO fix any
failure this PR caused — verified against a real baseline (revert the touched
files to their pre-PR versions), never by stashing uncommitted work, which
cannot rule out already-merged changes.

### Safety and stopping

- Expected workflow outcomes are typed values, not normal exceptions.
- Preserve historical artifacts unless explicitly authorized otherwise.
- Never merge a PR that the operator has reserved for their own approval.
- Stop immediately before that merge and report merge readiness.

### Context continuity

- Update this file after every semantic checkpoint.
- Update it after any material audit finding, policy clarification,
  implementation deviation or unexpected test failure.
- Update it before long tests, Gate runs, branch changes, rebases, conflict
  resolution or context compaction.
- When uncommitted work exists, record its exact file list, diff stat and
  deterministic diff fingerprint.
- After compact or resume, audit the design document and recent commits
  before continuing.

<!-- FIRST_PRINCIPLES_END -->

<!-- SEMANTIC_HANDOFF_BEGIN -->
## Semantic Handoff

Only the main agent writes this. The hooks validate it and never invent it.

**This handoff belongs to exactly ONE pull request.** Compaction and
resume happen inside that PR as often as needed. When the PR reaches its
stop condition, set `CONTEXT STATE: CLOSED / AWAITING OPERATOR ACTION`.
A new PR does NOT continue this file's story — it starts from a fresh
Implementation Working Rules contract and a re-initialised handoff, and
reads everything the previous PR did from merged repository and design
state. Never append a second active PR block below an old one; there is
one active PR context.

Freshness fields — the hooks parse these exactly:

Handoff updated for HEAD: TODO
Handoff working-tree fingerprint: TODO
Design document synchronized: no
Design sync reference: TODO
Safe to compact: no

Turn-continuity field — the Stop guard parses this one:

Operator input required: no

## PR Identity

PROJECT / PR: TODO
PRIMARY DESIGN DOC: TODO
RELATED / BINDING DOCS: TODO
IMPLEMENTATION BASE: TODO
IMPLEMENTATION BRANCH: TODO
CONTEXT STATE: ACTIVE

## Current Objective

TODO — what THIS PR must achieve, in a few sentences.

## Frozen Policy and Non-Negotiable Decisions

TODO — the operator-frozen decisions this PR may not revisit.

## Completed Checkpoints

TODO — landed semantic commits, each with its SHA and one-line outcome.

## Current Checkpoint

TODO — the one thing in progress right now.

## Current Implementation State

TODO — branch, HEAD, what is uncommitted, what exists so far.

## Decisions Made and Why

TODO — bounded decisions taken during implementation, with the reason.

## Audits Performed and Evidence Found

TODO — what was audited and the file:line evidence it produced.

## Problems Encountered

TODO — failures hit, their diagnosis, and whether they are resolved.

## Deviations from the Design

TODO — none, or each deviation with its classification and authority.

## Validation Already Completed

TODO — tests actually run, with counts and wall times. Never claim more.

## Known Limitations and Deferred Follow-ups

TODO — what this PR knowingly does not do, and who owns it next.

## Genuine Open Policy Questions

TODO — none, or the decisions genuinely reserved to the operator.

## Exact Next Actions

TODO — the numbered steps a resumed session should take, starting with
recovering repository truth.

## Stop Conditions

TODO — the normal stop, plus anything that must halt for operator review.

## Design-Document Synchronization

The design doc is named ONCE, under `## PR Identity`. Do not restate it
here: the parser reads a field's FIRST occurrence, so a second copy
edited later would be silently ignored.

Synchronized against HEAD TODO and fingerprint TODO.
Sections written this refresh: TODO.
<!-- SEMANTIC_HANDOFF_END -->

<!-- GENERATED_STATE_BEGIN -->
<!-- GENERATED_STATE_END -->
