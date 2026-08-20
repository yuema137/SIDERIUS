# Step 10 / P6 — Three-Task Full-Chain Executable Closure (SKELETON)

## 0. Status

**SKELETON ONLY — NOT A DETAILED DESIGN. NOT FROZEN. IMPLEMENTATION NOT
STARTED. DETAILED DESIGN DEFERRED UNTIL P1 / P2a / P2b / P3 / P4 / P5 ARE
MERGED** (or otherwise at the parent-required final topology).

**Operator review (2026-08-20)**: skeleton status confirmed — no premature
detailed implementation plan; this document stays a landing place for
hand-offs until the semantic children merge.

Parent: Step-10 parent REVISION 2 (frozen), scope item **S8**, §20.3
(depends on "all of them"), §20.8 ("P6 is last, unconditionally"), §22.1
(P6 is the ONE child whose primary evidence owner is a real Gate), §22.2
(Q-10-5 = B).

This skeleton exists so the other children's hand-offs have a named landing
place. It deliberately contains **no source audit, no commit decomposition,
no touched-file plan, no Gate command** — those are meaningless before the
final merged topology exists to inspect.

## 1. Purpose

Prove that the final merged generic Step-10 topology executes the SAME
production orchestration contracts for **TIDMAD, Pets and DAVIS** — the
evidence child. P6 is evidence, not new semantics (parent §20.6: running the
closure before the semantic children land "would be exactly the claim this
design refuses").

## 2. Dependency

Detailed P6 design starts only after P1, P2a, P2b, P3, P4 and P5 are merged.
At skeleton time: P1 MERGED (`bcb17e45`); P2a FROZEN/not implemented; P2b
DRAFT; P3/P4/P5 DRAFT rev 1.

## 3. Non-goal — no new semantic contract

P6 adds NO new scientific semantic contract. If the closure discovers a
missing one (a value a task needs that no upstream child bound, a
declaration the framework cannot express), that is **upstream debt owned by
the child that owns the family** — it is recorded and fixed there, never
hidden as P6 runner logic.

## 4. The final genericity claim

All three tasks use the same composition boundary (P1's
`--task_composition` / `RunTaskComposition`), the same workflow, the same
metric interfaces (P2a ordering + P2b secondaries), the same Health
interfaces (08x + P4 declarations), the same interpretation interfaces
(09x + P3 evidence), and the same carried-state interfaces (09.5a + P5) —
differing ONLY through bound task/config/plugin values. Known inherited
hand-offs P6 must close or explicitly re-assign, recorded by the upstream
ledgers: composed-metric scoring for non-TIDMAD loop runs (P1 §12 →
P6/seam route), child-side availability of out-of-tree data-path plugins in
subprocesses (P1 §12 → P6/Step 12), and complete contrast-task Health
evidence through the generic route (P4).

## 5. Runner retirement (Q-10-5 = B, frozen by the parent)

The hand-written Pets/DAVIS full-chain/Gate runners retire **only after
every distinct claim they own has been enumerated and transferred** to a
generic-loop test/Gate owner. Narrow helpers/fixtures may remain where each
owns a distinct failure class; hundreds of lines of duplicate orchestration
may not survive under the label "harness".

## 6. Expected executable evidence

TIDMAD full chain · Pets full chain · DAVIS full chain — through the generic
loader/composition route; zero task-name-branch census still green; zero
task-specific generic-core edits; persisted artifacts complete for all three
(scores, Health evidence, interpretation, carried state).

## 7. Gate posture — TBD at detailed-design time

P6 is expected to own real executable/multi-task closure, so bounded real
evidence is likely REQUIRED (parent §22.1 assigns Gate 2 as P6's primary
owner; no TIDMAD-only Gate may support a genericity claim). Exact Gate
count, iteration depth, round depth, GPU workload and command lines are
**deliberately NOT frozen** until the final merged topology is inspected
against the gate standard.

## 8. Stop condition

Detailed P6 design is **BLOCKED until the semantic children land.** When
they have, P6's design session starts from a fresh source audit of the
merged topology — never from this skeleton's assumptions.
