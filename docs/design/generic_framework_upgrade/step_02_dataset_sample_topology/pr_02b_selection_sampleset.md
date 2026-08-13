# PR 02b — Selection & SampleSet semantics (Step 02, child 2 of 3)

## Status

**REVISION 2 — pending the parent's operator freeze. NOT FROZEN.
IMPLEMENTATION NOT AUTHORIZED.**

Parent: [`../step_02_dataset_sample_topology.md`](../step_02_dataset_sample_topology.md).

Position in the DAG: **after 02a** (needs a resolved profile to inject).
Semantically independent of 02c, but the governance order is FROZEN as
`02a → 02b → 02c` so that aggregate Step evidence has a named owner —
02c is the Step FINALIZER (parent §6.2). This child therefore merges
SECOND and runs no Step-level Gate.

## 1. Scope

**OWNS**: strategy definitions (`snapshot` / `anchors` / `target` /
normal mode), per-family selection rules, the packing rule — including
making the trial packing asymmetry explicit — and the SampleSet JSON
round-trip contract at ONE boundary.

**DOES NOT OWN**: the profile itself (02a), the group map that `anchors`
selects with (02c — 02b consumes it), portions/seeds (runtime inputs,
never config), the resolved SampleSet as a stored artifact (runtime
state).

**Source starting point.** `sample_set_builder.py` hardcodes the
singleton three ways today: `DataScope.default().resolve(TIDMAD)`,
`list(range(TIDMAD.num_files))`, and `SEGMENTS_PER_FILE` reached
*through* `scoring_utils` rather than from the authority (parent §1.2).

## 2. Why this is a PR

After it merges, sample selection resolves its counts and index space
from the injected profile, so a different topology yields a correctly
shaped SampleSet instead of silently sampling TIDMAD's 200-segment,
20-file shape.

Its failure class is unique and severe: **a changed SampleSet shifts
every downstream experiment identity**, breaking comparability across
the whole chain. It owns an oracle no other child can red.

## 3. Compatibility contract

| Surface | Criterion | Baseline |
|---|---|---|
| Selection identity | the FIVE sha16 digests unchanged — three trial strategies at `seed=42, portion=0.05` full scope, plus normal mode and partial-scope snapshot — and the pinned first-five segment indices | **EXISTS** (`test_sample_set_builder.py`) |
| Scope equivalence | explicit full-range scope == `None` scope | EXISTS |
| JSON round-trip | key coercion behaviour unchanged at the boundary | **MISSING → capture first** |
| Packing | trial packing asymmetry (denoised local-index vs raw original-index) behaviour unchanged | **MISSING → capture first** |

The digests bind to CPython's `random.sample` implementation — a known,
accepted environment assumption already recorded in the test module.
Do not "improve" the sampling algorithm; that would invalidate every
historical experiment identity.

## 4. Checkpoints

| CP | Closing evidence |
|---|---|
| 0 | the JSON round-trip and packing pins captured BEFORE the change |
| A | the five digests byte-identical |
| B | **local Checkpoint B = the ESTABLISHED topology contrast (A1/A2) propagated THROUGH the SampleSet selection path** — a contrast topology must yield a correctly shaped SampleSet. No new axis, but this IS this child's Stage-B proof and is blocking, not a formality |
| C | the tuner builds a real run's trial and formal sample sets from the injected profile |
| D | targeted → affected package → focused integration/mutation → **exact-head CI**. No local full suite required (parent §9.1) |

**Mutations**: revert one consumer to the module constant and confirm a
digest reds; feed a contrast topology and confirm the shape follows the
profile rather than staying 20×200.

## 5. Gates

- **Gate 1 — NOT REQUIRED** (roadmap §17.0; assignment table: "New
  loader/renderer (pure Python)" → Unit only). Flip condition: rendered
  prompt bytes change.
- **Gate 2 — not run by this child**; once at Step level, owned by the FINALIZER 02c (parent §6.2).

## 6. Stop conditions

- any of the five digests changes;
- the sampling algorithm or seed derivation changes;
- portions or seeds migrate into config;
- a consumer keeps re-inting SampleSet keys its own way after the
  boundary pin lands.
