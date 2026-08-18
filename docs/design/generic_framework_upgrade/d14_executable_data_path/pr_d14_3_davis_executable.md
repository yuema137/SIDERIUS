# PR D14-3 — Track C executable: DAVIS future-frame prediction at L2→L3

**Parent**: `d14_executable_data_path.md` (FROZEN rev 3) §4.3 — instantiated,
nothing added beyond it. **Task authority**: roadmap §22.9a (frozen),
mirrored by `examples/davis_future_prediction/README.md`.
**Status**: **SELF-FROZEN rev 2 (2026-08-18)** — directive §12/§13; the
adversarial self-review produced the amendments recorded in place (§2.0
licence verdict from primary sources; §2.2 clip-rule edge cases; §2.5 the
MAE-family objective realized as `smooth_l1` — drafted at beta=0.01 and
AMENDED at C7 to the schema's minimum 0.1, see §2.5; §2.6 deliverable sizing). D14-delegated freedoms exercised where
the frozen text delegates them: the clip rule, the resize rule
(direct BILINEAR to 224×128, declared distortion), the reference
architecture, beta.

## 0. Source audit (at the D14-2 head)

| surface | state | evidence |
|---|---|---|
| seam + engine genericity + explicit-R3 leg | LANDED (D14-1, D14-2 C5b): non-TIDMAD tasks train through `run_experiment_streaming` with real R2+R3 | Pets Gate-2 PASS (D14-2 ledger §6 C6) |
| pack identity | FROZEN at PR0: `sequences.csv` **60 train / 15 validation / 15 final** (the 15/15 split is PR0's, NOT D14's), SHA-pinned; declared `ModelIOContract` `[B,3,8,128,224]f32 → [B,3,4,128,224]f32`; declared metrics mse(lower, presence-scoreability) / mae / psnr | `examples/davis_future_prediction/`; pack tests |
| clip identity | **D14-3's in full** (operator decision, PR0 review): deterministic `(sequence_name, start_frame)` windows, caps ≤8/≤4/≤4 per train/validation/final sequence | parent §4.3 |
| licence obligation | PR0: "D14 MUST verify and pin the exact terms applicable to the TrainVal-480p artifact" | `PROVENANCE.md` |
| engine losses | `LossConfig.loss_type ∈ {focal, focal_cw, ce, smooth_l1, custom}` — no bare "mae"; `smooth_l1` carries `beta` | `ml_models/models_format_sandbox.py:637` |
| metric handle | instances #1 (TIDMAD), #2 (accuracy); declared-spec rebind (`metric_spec_from_declaration`) | D14-2 C5 |
| plugin + governance | `examples/<pack>/plugins/*.py` sanctioned; loader env channel proven | D14-2 C4 |

## 1. Scope and homes

```text
tools/example_packs/fetch_davis.py                 NEW — fetch/verify DAVIS-2017-trainval-480p.zip
                                                   (official ETH host), SHA-256 recorded at first
                                                   fetch, machine-local --dest outside the tree,
                                                   idempotent, layout-checked extraction
tools/example_packs/davis_execution.py             NEW — derives the CLIP manifest (frozen rule
                                                   below, from DISK frame counts of the pinned
                                                   archive), the execution manifest (resize rule +
                                                   window probe hashes), and the nested gate
                                                   subset manifests
examples/davis_future_prediction/data/manifests/clips.csv         NEW, committed, SHA-pinned
examples/davis_future_prediction/data/manifests/execution.json    NEW, committed, SHA-pinned
examples/davis_future_prediction/data/manifests/gate2_{train,validation,final}.csv  NEW
examples/davis_future_prediction/plugins/davis_reference_predictor.py  NEW — plugin source
execute_tools/davis_data_path.py                   NEW — the DAVIS TaskDataPath implementation
                                                   (id "davis_future_prediction"); window reader,
                                                   npz deliverable codec; production manifest
                                                   parser (separability — the D14-2 C7 lesson,
                                                   applied from the start)
execute_tools/evaluation_metric.py                 EXTENDED — instance #3 `GlobalMseMetric`
                                                   (exact global mean over ALL elements — sums
                                                   and counts across clips, never mean-of-means)
scripts/run_davis_gate2.py                         NEW — the bounded Gate-2 runner
```

**Non-goals (parent §4.3, verbatim obligations):** no segmentation masks as
inputs; no optical-flow or augmentation machinery; no PSNR in the golden
path (optional observation only). Additionally: no chain/tuner binding, no
HealthGate work, no seam change.

## 2. The executable pieces

### 2.0 Licence verification (C1 — the PR0-frozen obligation; primary sources, 2026-08-18)

* `davischallenge.org` (downloads + main page): **no formal licence stated**;
  explicit research framing ("feel free to use the full resolution ones …
  in any step of your research") and a citation request ("Please cite the
  relevant papers in your publications if DAVIS helps your research").
* Official toolkit repo `davisvideochallenge/davis-2017` `LICENSE`:
  **BSD 3-Clause**, copyright Federico Perazzi 2016; the earlier
  `fperazzi/davis` README's recorded claim: "DAVIS is released under the
  BSD License".
* Challenge-created ANNOTATIONS: CC BY 4.0 (PR0-recorded) — **not consumed**
  (frames only, frozen task).

**Verdict: COMPATIBLE with the frozen intended executable path.** The use is
machine-local research evaluation of RGB frames with SHA-pinned provenance,
zero data redistribution (pins only in the tree), and the requested
citations already in `PROVENANCE.md`. Under BSD-3 this is plainly permitted;
the CC BY 4.0 annotations are unused; the download page adds only the
citation request. NOT a §13 stop. C1 pins these quotes + this verdict into
`PROVENANCE.md` verbatim.

### 2.1 Acquisition (C1)

`DAVIS-2017-trainval-480p.zip` (~833 MB) from
`https://data.vision.ee.ethz.ch/csergi/share/davis/DAVIS-2017-trainval-480p.zip`
(the official link on the challenge page), SHA-256 recorded at first fetch
into `PROVENANCE.md` + the fetch tool's constants (the executable
authority); machine-local dest `/home/klz/Data/DAVIS_2017/` on this box;
layout check: `DAVIS/JPEGImages/480p/<sequence>/%05d.jpg` for every
sequence named by the frozen `sequences.csv` (a missing sequence dir fails
closed). The root reaches the framework as the seam's `data_dir`.

### 2.2 The FROZEN clip rule (C2) — pure function, unit-proven on hand cases

For one sequence with `F` frames on disk and cap `N` (train 8 / validation 4
/ final 4): window length is 12 (8 context + 4 future, stride 1 inside the
window); the last legal start is `L = F − 12`; a sequence with `F < 12`
contributes ZERO clips (recorded per sequence in the clip manifest
generation output — not silently);

```text
n  = min(N, L + 1)
starts(n, L):  n == 1 → [0]
               else   → [ round(i · L / (n − 1)) for i in 0..n−1 ]   (even spacing,
                        first window at 0, last at L, ties by round-half-even)
```

Duplicates cannot occur for `n ≤ L + 1` (spacing ≥ 1). Committed
`clips.csv`: `sequence_name,start_frame,scope` (scope inherited from the
sequence's PR0-frozen scope), rows sorted `(scope, sequence_name,
start_frame)`; SHA-pinned; **sequence-disjointness across scopes is
re-verified at the manifest level AND at the reader** (leakage guard: a
clip's sequence must carry the scope the caller asked for).

### 2.3 Execution manifest + window reader (C3)

FROZEN transform: decode JPEG (PIL `.convert("RGB")`, no EXIF) → **direct
resize to (W=224, H=128), PIL BILINEAR** (declared: 854×480 aspect 1.779 →
1.75, a deliberate small distortion instead of a crop — recorded in the
manifest; frozen here by D14-3's delegated authority) → float32 `/255`,
CHW. A window stacks 12 frames → context `[3,8,128,224]` (frames
`start..start+7`) + target `[3,4,128,224]` (frames `start+8..start+11`).
`execution.json`: the rule fields + per-clip probe hashes (the FIRST train
clip of every 6th train sequence = 10 probes; sha256 over
`context.tobytes() + target.tobytes()`); two-process double-run proof.
Gate subsets: `gate2_train.csv` = first clip of every train sequence (60),
`gate2_validation.csv` = first clip of every validation sequence (15),
`gate2_final.csv` = first clip of every final sequence (15) — nested ⊂
`clips.csv` by construction, committed, pinned.

### 2.4 The DAVIS TaskDataPath (C4)

`execute_tools/davis_data_path.py`, id `"davis_future_prediction"`,
registered at import: `DavisClip(sequence_name, start_frame)`,
`DavisScope(rows)`; `load_davis_clips(path, scope=...)` — the
production-owned manifest parser (the D14-2 C7 separability lesson applied
from the start); datasets: lazy window decode per item, EXISTENCE of every
frame of every clip verified at construction (fail closed naming the first
missing frame — the exact-materialization obligation in clip vocabulary);
`train_portion < 1.0` refused (frozen task, no subsampling rule);
`max_samples` = deterministic prefix. Deliverable: ONE compressed
`predictions_{model}_{run}_{exp}.npz` mapping `"{sequence}:{start}"` →
float32 `[3,4,128,224]`; payload read = that mapping back. Absent file →
`{}` (scoreability owns refusal).

### 2.5 Objective + metric (C5)

* **Training/validation objective (R1/R3): `smooth_l1(beta=0.1)`**
  (**AMENDED at C7 from the drafted 0.01** — the frozen `LossConfig`
  validates `beta` in `[0.1, 10.0]`
  (`models_format_sandbox.py:644`) and REFUSED 0.01 at the first gate
  launch. A validated production constraint is never widened to fit a task,
  so the task takes the schema's MINIMUM — the most L1-like admissible
  setting. Honest trade-off, recorded: with values in [0,1] the quadratic
  region covers errors < 0.1 and the loss is linear beyond, so it is
  Huber/MAE-family with a wider deadband than drafted, not pure L1.) — the
  engine's shipped MAE-family objective (`LossConfig` has no bare L1; the
  directive's own wording is "L1 / MAE-family"); the stamped
  `objective_kind` will be `smooth_l1`
  (the L1 fixture's hand-authored `mae` label stays untouched beside it —
  cumulative corpus; the real-component variant records the REAL kind).
  Recorded as this design's §22.9a-delegated realization; the task's frozen
  SEMANTICS (dense L1-family regression on the future tensor) are unchanged.
* **Golden metric: instance #3 `GlobalMseMetric`** in
  `evaluation_metric.py` — generic dense-regression arithmetic:
  `_compute(deliverables, *, predictions, truth)` accumulates
  `Σ(pred−truth)² and Σcount` across clips and returns the EXACT global
  mean (the frozen aggregation: never an unequal mean-of-means); missing
  prediction for a truth clip is a loud ValueError (a partial dense
  deliverable is not meaningfully scoreable, unlike a classification miss);
  spec = the pack's DECLARED `metric_mse.json` via
  `metric_spec_from_declaration`. `id="mse"` passes the lexical rule
  (not loss-shaped — "mse" has no loss token; and the task genuinely scores
  its deliverable by MSE, the module's own documented carve-out).

### 2.6 Reference predictor (C6)

`plugins/davis_reference_predictor.py` — "known-good executable baseline":
predict `last context frame + residual`: a small `Conv3d` stack over the
context (3→16→16→3·4-shaped head) whose OUTPUT is ADDED to the last context
frame broadcast over the 4 future steps (~30 k params). The additive
last-frame baseline makes even an untrained net produce near-copy
predictions — a meaningful, finite MSE at gate budget. Config carries
`segmentation_size=128` as the recorded inert engine-residue field.

### 2.7 Bounded Gate-2 (C7)

`scripts/run_davis_gate2.py`, in-process binding, mirrors the Pets runner:
train on `gate2_train.csv` (60 clips, 2 epochs, batch 4) with
`task_eval_scope` = `gate2_validation.csv` (15 clips,
`validation_requested_rows=15`) → real R2+R3 → inference over
`gate2_final.csv` (15 clips) through the seam reader → npz deliverable →
payload → `GlobalMseMetric` → PASS evidence persisted. Work bounded before
start: 60 clips × 12 frames × 2 epochs ≈ 1 440 decodes + 30 optimizer
steps; ≤10 min with wide margin. PASS is functional: validated
R2+R3 (`comparability=established`, requested==materialized==15), 15/15
predictions, finite MSE ≥ 0 through the handle. OBSERVATION recorded:
MSE vs the trivial last-frame-copy baseline (computable from the same
payloads; not a pass condition).

### 2.8 Fixture upgrade + docs (C8)

Real-component `TrainingHistory`/diagnosis pair ADDED beside the L1 pair
(labels distinct; rung extended per the D14-2 pattern — the real variant's
`objective_kind="smooth_l1"` note explains the delegated realization);
STATUS → L2/L3 with evidence pointers; `data/README` deferred paragraphs
answered; census `_DATA_PATH_SURFACE` gains `davis_data_path.py`; the
parent-milestone §15.1 roadmap row note happens at the MILESTONE close
(parent instruction), not here.

## 3. Commit plan

| commit | content | validation before next |
|---|---|---|
| **C1** | fetch tool + archive SHA pin + licence quotes/verdict into PROVENANCE | offline unit tests (verify/mismatch/refusal); real fetch evidence; layout check green |
| **C2** | clip-rule pure function + committed `clips.csv` | hand-computed cases (F<12 → 0; n=1 → [0]; caps; even spacing; last==L); disjointness; pins |
| **C3** | execution manifest + reader transform + gate subsets | probe determinism two-process; window shapes; subset nesting |
| **C4** | `davis_data_path.py` + tests | scope refusal; existence fail-closed naming the frame; deliverable npz round-trip; probes THROUGH the seam |
| **C5** | `GlobalMseMetric` + rebind | arithmetic on known tensors (exact global mean vs a deliberately-wrong mean-of-means); missing-clip refusal; scoreability-before-arithmetic; declaration round-trip; TIDMAD+accuracy suites unchanged |
| **C6** | reference plugin + loader test | forward shape `[B,3,8,128,224]→[B,3,4,128,224]`; loads via env channel |
| **C7** | gate runner + spec-then-run + post-run record | Gate-2 PASS per §2.7 |
| **C8** | fixtures + STATUS/README + census surface | rung extended green; examples suite green; census green |

Targeted validation per commit (#221); full suite once at the single push's
exact-head CI.

## 4. Test-layer ownership

UNIT: clip rule, transform/probes, reader, codec round-trip, metric
arithmetic, census. GATE 1: **none** (no LLM-facing change). GATE 2:
REQUIRED bounded once (C7). CI: #221 selector; `execute_tools/` touch ⇒
full-suite PR run expected.

## 5. Adversarial self-check

* **Leakage**: scopes are sequence-disjoint at PR0; the clip manifest
  inherits scope from the sequence and the reader re-verifies — a clip can
  never cross scopes. No frame-level randomness anywhere (no RNG in the
  rule at all).
* **TIDMAD-shaped abstraction**: clip scope ≠ file/segments; npz mapping ≠
  per-file h5; global-mean MSE has no per-file vector. Nothing forced into
  TIDMAD vocabulary.
* **Self-referential expectations**: probe hashes committed once,
  byte-immutable; clip-rule expecteds hand-computed; metric expecteds on
  hand-built tensors.
* **Objective honesty**: `smooth_l1(beta=0.01)` is recorded as the
  MAE-family realization with its deadband stated — never silently labelled
  "mae"; the stamped kind is what the record carries.
* **Gate bounds before start**: fixed committed subsets; no fraction-based
  sizing anywhere.

## 6. Ledger

(appended per commit during implementation)

### C1 — licence discharged, archive pinned, acquisition tooling (landed 2026-08-18)

* **The PR0 licence obligation is DISCHARGED** (§2.0): four primary sources
  re-checked on the fetch date and pinned VERBATIM into `PROVENANCE.md`
  with the verdict, the no-redistribution fact, and the re-check trigger.
  **COMPATIBLE — not a §13 stop.**
* **Archive pinned:** `DAVIS-2017-trainval-480p.zip`, 832 766 765 bytes,
  sha256 `e3d0b5b7…`, fetched 2026-08-18T21:03:15Z from the official ETH
  host; extracted to `/home/klz/Data/DAVIS_2017/` (machine-local, outside
  the tree); **layout verified: all 90 sequences named by the frozen
  `sequences.csv` present with frames.**
* **Shared acquisition machinery** `tools/example_packs/_fetch_common.py`
  (the in-passing genericization rule — two consumers now): pins as
  constants, verify-before-anything, never re-download over evidence,
  layout-checked extraction for BOTH tar.gz and zip, in-tree `--dest`
  refused. `fetch_oxford_iiit_pet.py` migrated onto it (its 7 tests pass
  with one helper updated for the shared `url` field);
  `fetch_davis.py` is new.
* **`execute_tools/davis_data_path.py` opened** with the production-owned
  manifest parsers (`load_davis_sequences` / `load_davis_clips` with its
  scope filter = the reader half of the leakage guard) — the D14-2 C7
  separability lesson applied from the start, so the fetch tool's layout
  check consumes production, never pack tooling.

**Recorded deviation.** The pack test's `LICENCE_PINS` pinned the PR0
OBLIGATION sentence; discharging it necessarily removes that sentence, so
the pin MOVED to the discharge (verdict + BSD-3 + zero-redistribution +
annotations-not-consumed). The guard's defect class is unchanged: losing
the licence record still fails.

**Validation:** 113 passed (examples suite; deselect = the pre-recorded
local-only Pets stray-file guard) — new DAVIS tool suite (zip verify/
extract/idempotency, corrupt-zip refusal, four layout-check cases,
in-tree refusal, pin↔PROVENANCE mirror), migrated Pets tool suite, all
pack pins. ruff clean.

### C2+C3 — clip rule, clip manifest, execution manifest, gate subsets (landed 2026-08-18)

`clip_starts(frame_count, cap)` is the pure frozen rule (no RNG, no disk);
`count_sequence_frames` supplies the only disk input. **600 clips** —
60 train × 8 + 15 validation × 4 + 15 final × 4 exactly, i.e. EVERY frozen
sequence is longer than one 12-frame window (the too-short branch exists,
is tested, and reports non-silently — it just never fires on DAVIS
TrainVal). Gate subsets = first clip of every sequence (60/15/15).
`execution.json` carries the transform + window + clip-rule declarations
and 10 window probe hashes (first clip of every 6th train sequence).
Regeneration proven byte-stable (identical shas across two runs); all five
artifacts committed and PINNED as literals.

**Validation:** 31 hand-computed clip-rule cases (too-short → `()`,
exactly-one-window → `(0,)`, cap-binds spacing table `(0,14,29,43,57,71,86,100)`
hand-derived, available-windows-bind, validation-cap table, rounding cases,
and a 21-cell invariant grid: count, uniqueness, ascending, endpoints,
bounds) + 18 manifest/transform cases (pins; the 600/480/60/60 counts;
**sequence-scope disjointness = the leakage guard at manifest level**;
per-sequence re-derivation through the pure rule; nested gate subsets;
synthetic frame/window shape + EXACT slice identity against independently
decoded frames — no JPEG tolerance anywhere; missing-frame fail-closed;
REAL probe parity in this process AND a second process). Examples suite
162 passed.

**Recorded deviation.** The PR0 guard
`test_no_clip_manifest_and_no_frame_bytes_under_the_pack` forbade any
clip/window manifest — the deferral D14 owns. Re-scoped (renamed) to
enumerate the exact landed manifest set; the raw-bytes prohibition is kept
verbatim and permanent. Same defect class, current scope.

### C4+C5 — seam suite + GlobalMseMetric (landed 2026-08-18)

Seam (12 tests): explicit-binding resolution; foreign-scope refusal; frozen
window shapes with **input shape ≠ target shape** (Amendment 1 in its
second, different form); a clip whose window runs past the last frame fails
closed; portion refusal; prefix cap; npz round-trip preserving clip
identity and narrowing to float32; absent → `{}`; one naming rule both
directions; the scope filter proven disjoint across all 600 clips; REAL
probe parity THROUGH `training_dataset`; `truth_windows` byte-equal to the
reader's targets (one decode authority for data and ground truth).

`GlobalMseMetric` (instance #3): accumulates Σ squared-error and Σ count and
divides ONCE. Its load-bearing test is the unequal-sample-size case where
**mean-of-means = 2.0 and the frozen global mean = 3.2** — a
mean-of-means regression cannot pass. Missing prediction and shape mismatch
are refusals (a dense deliverable has no defensible stand-in for an absent
sample, unlike a classification miss). 67 passed with all four step06
suites and the census unchanged.

### C6 — reference predictor (landed 2026-08-18)

`plugins/davis_reference_predictor.py`: Conv3d stack → mean over the context
time axis → per-future-frame residual ADDED to the last context frame,
`[B,3,8,128,224] → [B,3,4,128,224]`, `PLUGIN_OUTPUT_TYPE="regressor"`.
3 tests: real-loader registration (incl. the output-type registry), the
declared contract boundary, and the baseline property — **zeroing the head
makes the prediction EXACTLY the last context frame repeated**, which is
what guarantees a finite meaningful MSE at gate budget.

### C7 — bounded Gate-2: **PASS** (2026-08-18)

**Spec** (as §2.7, unchanged): committed subsets 60/15/15 clips, 2 epochs,
batch 4, in-process binding, cuda, ≤10 min; functional PASS = validated
R2+R3 with `comparability` stamped and requested==materialized==15, 15/15
predictions, finite MSE ≥ 0 through the handle; baseline comparison is an
OBSERVATION.

**FINDING (attempt 1 — a real design defect, caught by production).** The
drafted `smooth_l1(beta=0.01)` was REFUSED by `LossConfig` (validated range
`[0.1, 10.0]`, `models_format_sandbox.py:644`) before any training ran —
the frozen schema doing its job. DECISION: take the schema's minimum
(`beta=0.1`), never widen a validated production constraint for a task;
§2.5 amended with the honest trade-off. Attempt 1's log is retained beside
attempt 2's evidence as the diagnostic record.

**Attempt 2 — PASS** at `df3b9623`, evidence
`/home/klz/Data/SIDEREIS_DATA/d14_davis_gate2_20260818b/`
(`gate_evidence.json`, npz deliverable sha `ee52a710…`, model, log):

* **Training (REAL, production engine under the DAVIS binding):** 6.79 s ·
  `objective_kind="smooth_l1"` · R2 = [0.049537, 0.047689] ·
  R3 = [0.044430, 0.044297] over 15 clips (requested == materialized) ·
  per-pass ~0.55 s · `comparability=established`.
* **Inference through the seam reader:** 15/15 clips, 0.51 s; npz
  deliverable written and read back through the codec.
* **Global MSE through the Step-06 handle** (spec = the pack's declared
  `metric_mse.json`): **0.0172898** — and the OBSERVATION the runner
  computes alongside it: the trivial last-frame-copy baseline scores
  **0.0173923**, so after 30 optimizer steps the reference predictor is
  already *better than copy* on unseen sequences. Not a pass condition;
  recorded because it is real evidence that the loop is wired to something
  that learns.
* **Wall:** ≈ 8 s end-to-end — far inside the bound.

Every stage of parent §4.3's required path executed REAL: licence-verified
pinned source → sequence + clip manifests → window reader → reference
predictor → training → validation → inference → dense deliverable →
Step-06 handle → global MSE. **Track C is EXECUTABLE.**

### C8 — cumulative-corpus fixtures + docs sync (landed 2026-08-18)

Real-component fixture pair ADDED (L1 pair KEPT verbatim): the REAL gate
run's history (`objective_kind="smooth_l1"`, the real resolved fingerprint,
15/15 validation rows) + the hand-computed diagnosis. The rung is now
PARAMETRIZED over both executable packs, and the DAVIS variant contributes
an input class neither the L1 fixtures nor the Pets variant had: **a MIXED
trend pair** — train DECREASING (r = 0.0373 > tol) with validation FLAT
(r = 0.0030 ≤ tol). The corpus check is parametrized too, so "the L1 pair
survives" is executable for both packs.

STATUS.md → **L2/L3 EXECUTABLE** with every previously-deferred row moved to
LANDED and its evidence named (clip identity, reader/execution manifest,
reference plugin, gate subsets, **licence verified**); `data/README.md`'s
two deferral paragraphs answered with the decided mechanisms.

**Validation:** examples suite **136 passed** (deselect = the pre-recorded
local-only Pets stray-file guard). ruff clean.

### C9 — the dispatched-CI corrections (2026-08-18)

Two defects that ONLY the dispatched CI run could find (stacked PRs get no
CI — issue #233; local pyright cannot run here):

1. **17 pyright errors** across D14-2/D14-3 — fixed at the boundary, none
   suppressed, both gates re-run to prove runtime neutrality (Pets 0.0270,
   DAVIS 0.017290, identical). Details in the two fix commits.
2. **A THIRD maturity pin of the same family**, in a directory my local
   chunks had not covered:
   `tests/unit/core/test_pr07c_capability_routing.py::test_no_execution_maturity_was_added`
   asserted `list(pack.rglob("*.py")) == []`. RE-SCOPED exactly like the
   other two sites — sanctioned plugin source at
   `examples/<pack>/plugins/*.py` only; the `resolved/` prohibition and
   07c's "adds no adapter/profile/download" claim are untouched. **My
   chunking gap, honestly recorded:** the local sweep covered
   execute_tools / examples / guardrails / agent / nodes / ml_models /
   tools but NOT `tests/unit/core`, `scripts`, `workflows`, `dashboard` —
   those are now run too.


### FINAL STATE — D14-3 (terminal closeout, 2026-08-18)

**Draft PR #232**, branch `d14-3-davis-executable`. This branch is the
milestone's top of stack, so its head is the FINAL D14 head: final code +
final docs are committed FIRST, and the exact-head CI dispatch happens on
that SHA (the operator's ordering — a green run predating the last docs
commit belongs to the previous head and is recorded as such, never as this
head's evidence). The final SHA and CI run id are reported in the review
packet, in the PR thread and in the handoff; they cannot appear in the
commit they describe.

Acceptance, all met: **licence verified from four primary sources and pinned
verbatim, verdict COMPATIBLE** (BSD-3 toolkit; research framing + citation
request; CC BY 4.0 annotations NOT consumed; zero redistribution) · archive
SHA-pinned, 90 sequences layout-verified · frozen pure clip rule → 600
committed clips, sequence-disjointness enforced at manifest AND reader ·
window reader + execution manifest with two-process probe parity ·
reference predictor with the proven last-frame-copy baseline property ·
global MSE as Step-06 instance #3, mean-of-means excluded by a
discriminating test · **Gate-2 PASS** (real R2+R3, 15/15 dense
predictions, MSE 0.017290 **beating** the trivial baseline 0.017392) · L1
fixtures kept, real-component variants added, rung parametrized over both
executable packs.

**Milestone-level record, cross-task validation, residual risks and the
Step-08 readiness answer live in the parent `d14_executable_data_path.md`
§7a–§7a.3.**
