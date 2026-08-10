# PR G — Capability-derived inference batch

**Status: DESIGN FROZEN — operator approved for implementation
(2026-08-10). This document is now the LIVE engineering ledger for the
PR G implementation; sections below are updated as the work proceeds.**
Rev 1 found the capability-derived mechanism already live on the agent
runtime path; rev 2 narrowed the scope to forecast/identity coherence.
Rev 3 (final small audit, §0.R.9-0.R.12) resolved the operator's four
remaining questions with exact source arithmetic: the "exact
cancellation" claim was CORRECTED to bounded-residual invariance (ceil
semantics, §0.R.9); the time-gate rejection consequence is traced and
the reachability language made precise (candidate EXECUTION reachability
can change — intended; hypothesis GENERATION reachability cannot,
§0.R.10); the real Gate is frozen to require the
`training_warmup_x2.7_fallback` forecast source (§0.R.11); and the
training-phase identity hash/cache is PROVEN insensitive to the
inference-batch payload field (outcome A, §0.R.12). **Operator freeze
(2026-08-10): Q-G-1 APPROVED; Q-G-2 APPROVED/FROZEN; Q-G-3
APPROVED/FROZEN — Option A; Q-G-4 APPROVED (narrowed contract-test +
comment-truth form); Q-G-5 APPROVED. Implementation authorized; DO NOT
MERGE until operator review.**

**Rev 3 final reconciliation (2026-08-10, operator-directed; source-grounded,
no implementation).** Two closures make the correctness story exact:
(1) **The forecast error is two-sided, not "always conservative."** The
production probe resolver's candidate set is `(64,32,16,8,4,2,1)`
(`batch_resolver.py:58`) with NO floor and no `≥25` guarantee (§0.R.10a) — a
candidate reaching inference can run at B < 25. The old table=25 forecast is then
`ceil(total_ml/25)`: for probed B > 25 it OVER-prices (→ false `skipped_time_risk`
rejection, ≤ 64/25 = 2.56×), for B < 25 it UNDER-prices (→ **false time-risk
ACCEPTANCE** — a plan whose real inference time exceeds the budget is admitted;
up to ~25× at the reachable minimum B=1). G2's real invariant is therefore **the
time gate must price inference at the batch that will actually run**, not merely
"make the forecast less conservative." (2) **The per-file ceil residual is bounded
from source** (§0.R.9): `runtime = Σᵢ ceil(mlᵢ/B)`, `estimator = ceil(Σᵢ mlᵢ/B)`,
difference ≤ `n_files − 1` steps (estimator always UNDER-counts); worst supported
grid ≈ 21.9 % of runtime, default trial ≤ 2.4 %, default seg 40000 ≈ 1.08 % —
second-order beside the ×2.7 path's 2.5×–25× factor. Every "exactly cancels" /
"always conservative" statement is corrected in place below. **Q-G-2 conditions
discharged; Q-G-3 frozen APPROVED — Option A.**

| | |
|---|---|
| Plan section | `docs/design/v21_priorities.md` — PR G section + P5 + §E.3d (binding, incl. §E.3d.11-12) + §E.4 |
| Gate | **NOT a V21 launch blocker.** No score/metric change; no hypothesis-GENERATION change. Candidate EXECUTION reachability CAN change — intended: G2 makes the time gate price inference at the batch that will actually run, correcting the ×2.7-path forecast's **two-sided** error — wrongful `skipped_time_risk` rejection when the probed batch > 25, and wrongful admission when it is < 25 (§0.R.10, §0.R.10a) |
| Depends on | PR F merged (`fd7c8816`) — no code dependency; PR B's S3 semantics and PR C's O-C-2 ownership line are frozen inputs |
| Audit date | 2026-08-10, against master `c1925586` |

> **Fresh-audit rule (§E.5):** PR G starts from this audit, never from
> the old ledger premise. The ledger's own update block predicted this:
> *"The measurement PR G wants may already exist (§E.3d.1) … audit that
> path before designing a new derivation."* The prediction was correct —
> see §0.A. This is the **eighth** occurrence of the §E.3d.1 shape
> (a correct mechanism that callers don't — or only partially — use).

---

## A0. Verification toolchain

```bash
# Same toolchain as PRs D/E/F (§E.3d.12: every checker at every final head)
.venv/bin/python -m pytest <targets> > /tmp/pytest.log 2>&1; echo rc=$?
.venv/bin/ruff check . && .venv/bin/ruff format --check .
PYRIGHT_PYTHON_GLOBAL_NODE=off uv run pyright
```

Full suite only at PR completion from a clean tree; verdicts from the
log, never a wrapper exit code.

---

## 0. Pre-design audit (all claims carry file:line evidence)

### 0.A The §E.3d.1 question, answered: the mechanism EXISTS and is LIVE

The probe-driven, name-blind batch selector is
`agent/skills/evaluate_vram_skill/batch_resolver.py` (Phase 6.6 §3.5) —
its own docstring says it *"replaces the deprecated
`_INFERENCE_BATCH_SIZES` table with a probe-driven search"*, it reads no
model-type strings (Principle 2, enforced by
`tests/unit/guardrails/test_no_model_name_branches.py`), and its chosen
batch **already reaches production inference on the agent path**:

```text
run_production_preflight                    (tuner :4541)
  -> evaluate_vram_skill wrapper 6a          "inference_batch": <probed>
  -> resource_check["inference_batch"]       (tuner :4695)
  -> active_params["inference_batch"]        (tuner :4696, Phase 6.6 A.11)
  -> inference_skill wrapper                 (wrapper.py:22 forwards it)
  -> sandbox_executor.execute_inference      (:1543 — "authoritative
     runtime batch" when not None; table fallback ONLY when None)
```

One attempt loop serves both trial and formal rounds (the K9 workflow
test pins hint/flag preservation across the trial→formal boundary), so
**formal inference also runs at the probed batch**. P5's runtime cost
("generated models fall back to conservative batch 25, slowing
inference") is therefore **already fixed on the agent path** — the
fallback fires only where no hint is passed.

**Previous assumption** (ledger objective): *"Derive the inference batch
from a candidate's measured memory profile rather than a name-keyed
table"* — implying the derivation must be built.
**Audit evidence:** the derivation exists, is name-blind, and is the
authoritative runtime batch on the agent path.
**Corrected understanding:** PR G's real work is (i) the **forecast**
and the **measurement identity** still read the table while runtime
uses the probe — a live coherence gap; (ii) the executor's fallback
migration (A.7→A.9) was never completed and its comments are stale.

### 0.B Complete consumer census of `inference_batch_for` / the table

Every non-test consumer of `core/inference_defaults.py`, classified:

| # | Site | Role today | PR G disposition |
|---|---|---|---|
| 1 | `core/sandbox_executor.py:1543` | **Fallback only** — used iff `inference_batch is None`; comment says "A.9 will remove the fallback once every caller has been migrated" (migration never completed) | G4 (Q-G-4, final): **NO new runtime observability.** Keep the fallback value unchanged; pin by CONTRACT test that every feasible/CPU-mode agent-path `resource_check` return carries `inference_batch: int ≥ 1`, so the fallback is unreachable by construction on the agent path (reachable only from no-hint baseline/legacy or a contract bug). Comment/docstring truth only. *(Supersedes the rev-1 "observe loudly on agent paths" proposal, which is withdrawn.)* |
| 2 | `agent/skills/inference_skill/estimator.py:118,240` | **Planning forecast** — VRAM/wall-time forecast at the TABLE batch | G1/G2: accept an explicit batch; tuner passes the probed one |
| 3 | `agent/skills/evaluate_time_skill/wrapper.py:746` | **Time-gate forecast** — inference wall-time at the TABLE batch, while the probed batch is ALREADY in `active_params` when this gate fires (set :4696, gate fires :4699+) | G2: prefer the hint |
| 4 | `core/runtime_control/gpu_measurement_identity.py:172-174` | **Measurement identity** — `resolve_inference_batch` returns the table value; its comment claims it is *"THE canonical source, and the same one `execute_inference` uses"* — **stale**: `execute_inference` prefers the hint | G3: prefer an explicit hint; fix the comment |
| 5 | `core/runtime_control/estimator.py:153,171` | Metadata only (`fallback_inference_batch`) | unchanged; comment sync only |
| 6 | `scripts/run_comparison.py:227,427` | **Baselines** — no hint passed; table entries are paper/VRAM-calibrated for the builtin types | intentionally unchanged (Q-G-1) |
| 7 | `scripts/c2_prephase_validation.py`, `scripts/pregate_runtime_control_validation.py` | Historical validation scripts | unchanged; documented |

> **Rev-2 note:** the disposition column above is rev-1 history. Final
> dispositions after the §0.R source audit: row 1 → **no new
> observability; contract test + comment truth (0.R.6)**; rows 2-3 →
> **G2 threads the SAME explicit batch into BOTH consumers (0.R.3)**,
> and `estimate_peak_bytes` (inference) is production-dead (0.R.2);
> row 4 → **payload-truth + latent-trap closure only (0.R.5)**.

Note on #4: the measurement worker supports inference-phase
measurements (`gpu_measurement_worker_main.py:270,506`), but the tuner
today requests **training-phase measurements only** (`:774,:4961,:5000`;
the `phase="inference"` strings at `:5037,:5059` are record labels, not
requests). The identity divergence is therefore a **latent trap**
(documented at `gpu_measurement_identity.py:85-98`: a wrong-batch
inference measurement once produced a 3.47× under-read), not a live
production defect. G3 closes it before it can fire.

### 0.C The live coherence gap (the actual defect PR G fixes)

For any model where the probed batch ≠ the table/fallback value —
**every generated model** (no table entry → fallback 25, probes
frequently resolve 64) and any builtin where the probe disagrees —
the inference **wall-time forecast** feeding the time gate is computed
at the wrong batch while runtime uses the probed one. Consequences:
time-gate decisions priced on a batch that will not run, and the
`inference_ms = hint × inf_batch / ml_per_psd` scaling (:749) applies
the wrong multiplier to a *measured* per-segment cost. This is
throughput-forecast correctness — squarely PR G's O-C-2 ownership
(throughput), not admission (PR C) and not S3 semantics (PR B).

> **Rev-2 correction, superseded by rev-3 §0.R.9/§0.R.10a:** the
> order-of-magnitude divergence is confined to the `training_warmup_x2.7`
> fallback path; on the measured-hint and static paths the batch does not
> cancel exactly but leaves only a **bounded partial-batch residual**
> (≤ `n_files − 1` steps; §0.R.9). The ×2.7 gap is **two-sided, not always
> conservative**: table=25 over-prices when the probed batch > 25 (false
> rejection) and under-prices when it is < 25 (false admission) — probed
> batches below 25 are reachable (§0.R.10a).

### 0.D What C3b actually pins, and how PR G must move it

`tests/unit/core/test_inference_batch_absence_is_observability_only.py`
pins two properties:
1. *Planning and runtime agree on the batch for an unregistered model* —
   proven via both calling `inference_batch_for`. **This is now a
   partial truth**: it holds for the no-hint pair, while the real agent
   path prefers the hint on the runtime side only. G2 RESTORES the
   spirit of this pin (forecast == what actually runs) by feeding both
   sides the same probed batch; the test must be extended, not deleted.
2. *`inference_batch_uncalibrated` reaches observability surfaces only,
   never a predicate.* PR G must preserve this verbatim — a
   capability-derived batch must not turn the flag into a pricing or
   admission input.

### 0.E The old ledger scope/merge criteria are wrong as stated

The ledger PR G section says *"remove the name-keyed fallback"* /
*"name table removed from the path"* and *"outputs byte-identical"*.
Audit verdict:
- **The table must stay** for baselines: entries are calibrated for
  memory reasons (`transformer: 1` for O(T²) attention;
  `rnn: 10` — comments at `inference_defaults.py:38-41`), the ledger's
  own update block forbids deleting it ("the lazy over-fix C3b's test
  already guards against"), and `run_comparison.py` passes no hint.
- **"Byte-identical inference outputs"** is not a sound criterion
  *across a batch change*: identity is only guaranteed when the batch
  is unchanged. Where PR G changes nothing (no-hint paths, hint==table)
  outputs must be byte-identical; where the batch legitimately differs,
  the frozen scorer contract — not raw output bytes — is the invariant
  that must be shown untouched. Restated criteria in §4 (Q-G-5).

### 0.R Revision 2 source audit (operator-directed, 2026-08-10; read-only)

Every rev-1 assumption below is preserved as
*assumption → audit evidence → corrected understanding*.

#### 0.R.1 The G1 parity contradiction — resolved: no new key, ever

Rev-1 proposed adding `inference_batch_source` to the breakdown while
also requiring no-hint deep-equality — contradictory. Audit of the
actual breakdown shapes (`estimator.py:155-164, 287-296`) and their
consumers: the authoritative batch already reaches the record surface
via `record_params["inference_batch"]` (tuner :4697), so a source field
adds nothing a reviewer cannot already read. **Corrected design: G1
adds NO new output key on ANY path.** The explicit argument, when
supplied, replaces the VALUE of the existing `inference_batch`
breakdown key; `inference_batch_uncalibrated` keeps its registration
meaning untouched. No-hint deep-equality becomes trivially true.

#### 0.R.2 The complete forecast-consumer call graph

Production callers of the inference estimator's two entry points:

| Caller | When it runs | Hint available? | Live? | PR G action |
|---|---|---|---|---|
| `evaluate_time_skill/wrapper.py:758` (via :746 batch, :749 conversion) | tuner attempt, AFTER the hint is captured at :4696 | **yes** | live agent path | **G2 threads it — into BOTH the wrapper and the estimator (see 0.R.3)** |
| `agent/utils/proposer_preflight.py:182` (caller: `ml_model_proposal_agent.py:211-215`) | proposal time, before any tuner attempt exists | **no — by construction** (no realized candidate, no probe) | live but `advisory_only: True`, `provenance: "static_uncalibrated"`, static path only | none — and the static path is batch-invariant (0.R.3), so the table value cannot mislead it |
| `estimate_peak_bytes` (inference, `estimator.py:90`) | — | — | **ZERO production callers** (grep-proven); the live inference-VRAM forecast is the structural probe inside `evaluate_vram_skill` | none — documented as dead on the forecast path; its table read is unreachable |

Precise invariant (rev 3): after G2, the only live forecast consumer
still READING the table is the proposer's advisory estimate — which is
`advisory_only`, has no hint by construction, and sits on the
static path whose batch sensitivity is the bounded ceil residual only
(0.R.9). No live consumer remains for which a probed batch exists but
the table is used instead.

#### 0.R.3 The time-forecast formula — units proven from source

**Producer of the hint** (`wrapper.py:213-222`): median over post-warmup
files of `elapsed_ms / n_psd_segs` from the PREVIOUS trial round's real
inference sidecar — **wall-milliseconds per PSD segment, measured at
the batch that inference actually ran** (the probed batch, on the agent
path). Throughput is baked into the measurement.

**Conversion** (:749): `ms_per_step = hint × inf_batch / ml_per_psd`
where `ml_per_psd = PSD_SEGMENT_LENGTH // seg_size` (ML segments per
PSD segment) and `inf_batch` = ML segments per step. Units check:
(ms/PSD-seg) × (ML-seg/step) / (ML-seg/PSD-seg) = ms/step. ✓

**Consumer** (`estimator.py:212-296`):
`seconds = ceil(total_ml / inf_batch) × ms_per_step / 1000`.

**The decisive algebra (CORRECTED by rev 3 §0.R.9 — production uses
`ceil`, not real division):** in the measured-hint path,
`seconds = ceil(total_ml/B) × (hint × B / ml_per_psd)/1000` — the batch
does NOT cancel exactly; it cancels **up to the final-partial-batch
residual**. Because runtime executes per file while the estimator takes
one global ceil, the exact residual is bounded by `n_files − 1` steps
(§0.R.9), which is ≤ 2.4 % of the step count at the default trial and a
supported-grid worst case of ≈ 21.9 % — small either way. The same
bounded residual applies to the static path (`ms/step` exactly linear in
B). **The middle fallback path** (`training_warmup_x2.7`: ms/step from a
training measurement, batch-independent; steps = ceil(total_ml/B)) is the
only ORDER-OF-MAGNITUDE batch-sensitive path, and its error is
**two-sided**: the forecast at table=25 vs runtime at the probed batch B
differs by the factor `ceil(total_ml/25)/ceil(total_ml/B)` — **> 1 when
B > 25** (over-price, e.g. 25→64 ≈ 2.5×, → 2.56 asymptotically: false
time-risk rejection), and **< 1 when B < 25** (under-price: false
time-risk admission — reachable, §0.R.10a; ~25× at the minimum B=1). It is
NOT always conservative. PROVIDED the wrapper's `inf_batch` (:746) equals
the estimator's internal one (:240) — today both call
`inference_batch_for`; G2 must keep both sides equal explicitly.

**Previous assumption** (rev 1): the time forecast diverges from
runtime for every model where probed ≠ table.
**Corrected understanding (rev 3 final):** the order-of-magnitude
divergence is REAL and confined to the ×2.7 fallback path (first
iteration / OOM-killed trial / degenerate sidecar — exactly generated
models' early rounds), where the forecast prices inference at table=25
while runtime uses the probed batch. The error is **two-sided**: for a
probed batch > 25 the forecast OVER-prices (up to 64/25 ≈ 2.56× — wrongly
rejects on time); for a probed batch < 25 it UNDER-prices (a plan whose
real inference time exceeds the budget is wrongly admitted). The
measured-hint and static paths carry only the bounded per-file ceil
residual (0.R.9), not exact cancellation.
**Two G2 consequences:** (1) the fix is justified as a **two-sided
pricing correction** — it makes the gate price inference at the batch
that will run, not merely a less-conservative forecast; (2) **G2 MUST
supply the SAME explicit batch to both the wrapper (:746) and the
estimator (:240)** — changing one side only would break the two sides'
same-batch coherence and corrupt the currently-correct forecast by the
probed/table ratio. A test pins the both-sides invariant.

#### 0.R.4 `active_params` lifetime — stale hint impossible by construction

`active_params` is constructed FRESH inside the attempt loop (:4452,
the single construction site), from the current plan, WITHOUT an
`inference_batch` key; the only write is :4696, after the current
attempt's feasible resource check. A later attempt that produces no
batch has a rebuilt dict with no key — a previous attempt's value
cannot survive. `.get("inference_batch")` is therefore sound. G2 still
adds the cheap negative test (hint-less attempt following a hinted
attempt → wrapper receives None) to pin the construction property.

#### 0.R.5 G3 ordering — the hint is already in scope, but the live path is training-phase only

Proven order inside one attempt: preflight :4541 → hint captured into
`active_params` :4696 → time gate :4712 → **prephase measurement
:4917** (which RECEIVES `active_params`, hint included) → training →
inference :5031. The helper then ignores the in-scope hint and
re-derives from the table (:760). So structurally this is the
operator's outcome A — no reordering needed, the value is already an
argument away. **However:** the live path requests TRAINING-phase
measurements only (:774; the worker consumes `inference_batch_size`
only for `phase=="inference"`, `gpu_measurement_worker_main.py:270,
506`; `INFERENCE_COMPARABLE_FIELDS` applies to inference-phase
comparisons only). The table value is today EMBEDDED in the planned-
identity payload but INERT for comparison and for the worker.
**Corrected G3 claim:** on the live path, G3 changes only the recorded
planned-identity payload (it stops recording a batch that is not the
one production would run) and closes the latent trap for the future
inference-phase caller. It does NOT create a live
`measurement_batch == runtime_batch` equality, because no inference-
phase measurement is requested today — and the PR-level invariant is
restated accordingly (§4).

#### 0.R.6 G4 reachability — the agent-path fallback is UNREACHABLE by construction

Every route by which an agent attempt reaches `execute_inference`
carries a hint: the feasible probe path always includes
`inference_batch` (wrapper §6a return); the CPU-only early return
includes `"inference_batch": 1` (wrapper :582); `schema_violation` →
constraint-aware retry, no inference; `status="error"` → raise;
infeasible → skip record + `continue`; prephase infrastructure failure
→ terminal. The executor fallback (:1543) is reachable ONLY from
`run_comparison.py` baselines, legacy validation scripts, and a
hypothetical wrapper-contract bug ("if the wrapper somehow omits it",
tuner :4693-4694).
**Corrected G4 scope: NO new production observability** — a fact that
cannot occur on the agent path needs no record field. Instead: (a) a
CONTRACT TEST pinning "every feasible/CPU-mode resource_check carries
`inference_batch: int ≥ 1`" — making the unreachability durable and
loud at test time; (b) comment/docstring truth fixes (the executor's
":1518 A.9 will remove the fallback" narrative and the
`inference_defaults.py` consumer census).
*Recorded observation (not PR G scope):* this audit also explains the
pre-existing k9 integration failure — the "Feasible" verdict print
moved into the isolated preflight SUBPROCESS when PR A landed, so the
parent-process `capsys` assertion can never see it again.

#### 0.R.7 The real Gate must exercise the change

The bounded real validation's generated model MUST satisfy
`probe-derived batch ≠ 25` (the old fallback), so the demonstrated
contrast is `OLD forecast path (25-based ×2.7) → NEW (probed)` with
runtime unchanged — a degenerate probed==25 case would pass without
exercising G2. Selection is from the realized population's probe
results (PR F's harness evidence shows generated models commonly probe
to 64). Frozen scorer untouched, proven by the acceptance suite.

#### 0.R.8 Parity-matrix cost bound and hardware locality

The matrix reuses `resolve_inference_batch`'s CPU structural probe.
PR F's measured costs on this host bound it: builtin wavenet full
search 26–100 s per config; the 2.6 B gated_fno ~205 s. Six shipped
models at production seg sizes ≈ **10–20 min total, CPU-only** — cheap
enough to keep all six rows. The matrix is **hardware-local diagnostic
evidence on the lilab reference GPU/host (PR F's calibration
boundary), never a universal expected mapping**, and neither the
resolver nor the table changes because of it in PR G.

#### 0.R.9 The per-file ceil residual, bounded from source (rev 3 final; replaces rev 2's "exact cancellation" and rev 3's single-segment ≤2.4 %)

**Source facts.** `PSD_SEGMENT_LENGTH = 10,000,000`
(`execute_tools/dataset_config.py:293`; constants `SEGMENTS_PER_FILE = 200`,
`NUM_FILES = 20` at `:294-295, :302-304`). `ml_per_psd = 10,000,000 //
seg_size` → 250 at seg 40,000; 625 at seg 16,000; 200 at seg 50,000; legal
`seg_size` = the 36 divisors of 10 M in `[100, 100000]`
(`dataset_config.py:118-138`). The eval `SampleSet` is
`{file_index: [psd_segment_indices]}` (`execute_tools/sample_set_builder.py:8`)
with an **equal PSD count `P` per in-scope file** (normal mode = one file, 200
segs, `:115`; trial/snapshot mode `P = max(1, round(trial_portion × 200))`
applied identically per file, `:94, :100-102`; default `trial_portion = 0.1` →
`P = 20`; full scope → `n_files = 20`). So each file carries the **same**
`ml_i = M = P × ml_per_psd` ML segments.

**Runtime is per-file, the estimator is one global ceil.** Runtime loops
over files (`inference_single.py:559`) and, per file, batches `range(0, dim1,
bs)` with `dim1 =` that file's ML count (`:627, :636-645`) — so
`runtime_steps = Σᵢ ceil(mlᵢ / B) = n·ceil(M/B)`. The estimator computes
`n_psd = Σ len(v)`, `total_ml = n_psd·ml_per_psd`,
`ceil(total_ml / max(B,1))` (`estimator.py:174-177`) — one global ceil,
`estimator_steps = ceil(n·M / B)`.

**Exact bound.** Since `Σ ceil ≥ ceil Σ`, the estimator **always
under-counts**: `0 ≤ runtime_steps − estimator_steps = n − ceil(n·s/B)`
where `s = M mod B ∈ [0, B−1]`; this is maximised at `s = 1`, giving
`diff ≤ n − ceil(n/B) ≤ n_files − 1` steps — an **absolute** bound of
**≤ 19 steps** at the maximum `n_files = 20`, independent of B. As a
relative error `(runtime − estimator)/runtime` over the whole supported
grid (all 36 seg sizes, `n ≤ 20`, `P ≥ 1`, `B ∈ {64,…,1}`):
- **default trial** (`P = 20`): ≤ **2.4 %**; at the actual default seg 40,000
  (M=5000, n=20, B=64) it is `1580` vs `1563` → **1.08 %**; seg 16,000 → 0.33 %.
- **normal mode** (single file): **0 %**.
- **supported-grid worst case = ≈ 21.9 %** — the **exhaustively-confirmed
  maximum** over every reachable point (all divisor seg sizes, `P ∈ [1,200]`,
  `n ≤ 20`, `B ∈ {64,…,1}`; the `seg=100000` constraint forces
  `ml_per_psd ≥ 100 > B_max`, so the pathological `M ≈ B+1` corner is
  unreachable). One realising instance: seg 50,000 (ml_per_psd=200), `P = 1`
  (M=200), `n = 8`, `B = 64` → runtime `8·ceil(200/64) = 32`, estimator
  `ceil(1600/64) = 25` → 7 steps → **7/32 = 21.9 %** of runtime (several
  equivalent corners tie at 7/32). It requires an atypical small
  `trial_portion` (P=1); at that corner the whole inference is ~25–32 steps
  (sub-second), where the per-file **fixed** residual (inference_single.py:500,
  537) dominates the wall clock anyway.

**Conclusion.** The measured-hint and static paths carry only this
**bounded, always-downward per-file ceil residual** — ≤ `n_files − 1` steps,
≤ 2.4 % at the default trial, ≈ 21.9 % at an atypical worst case — which is a
**second-order** term beside the ×2.7 path's `ceil(total_ml/25)/ceil(total_ml/B)`
**factor** (`> 1` for B > 25, up to 2.56×; `< 1` for B < 25, down to 1/25 at
B=1 — §0.R.10a). Every "exactly cancels" / "always conservative" claim
elsewhere in this document is superseded by this statement and §0.R.10a.

#### 0.R.10 Time-gate rejection: the exact consequence, and precise reachability language

Traced flow (tuner :4829-4870): `feasible=False` → a
`skipped_time_risk` record is emitted, *"this attempt does NOT count as
a round"*, and the loop continues to the NEXT ATTEMPT — the planner
retries with a new plan informed by the verdict/suggestion; attempts
are bounded (`attempts_per_round`). M6 separates evidence-refusal from
a genuine time verdict (an infrastructure condition is never written as
candidate evidence). Formal rounds additionally carry the
bypass-time-budget gate for clear winners (:4774+). Consequences,
stated precisely: **hypothesis/proposal GENERATION reachability is
unchanged** (the proposer runs before and independently of this gate);
**candidate/plan EXECUTION reachability IS affected in BOTH directions**
(§0.R.10a) — (i) when the probed batch > 25, a plan whose ×2.7 forecast
wrongly EXCEEDS the budget is skipped without ever training, and repeated
wrongful skips can exhaust a round; (ii) when the probed batch < 25, the
×2.7 forecast wrongly UNDER-prices inference and a plan whose real
inference time exceeds the budget is admitted (a wrongful acceptance, not
a wrongful skip). G2's intended effect is that the gate prices inference
at the batch that will actually run — plans wrongly skipped when B > 25
can execute, and plans wrongly admitted when B < 25 are correctly gated.
This is the bug-fix purpose (a two-sided pricing correction), declared,
not a side effect; no score/metric and no GENERATION change.

#### 0.R.10a Reachability of a sub-25 probed batch (rev 3 final — closes the "always conservative" gap)

The claim "table=25 is always conservative / wrongly rejects, never
admits" holds only if a candidate that reaches inference cannot run below
25. Source says it can:
- The resolver's candidate set is
  `_DEFAULT_CANDIDATE_BATCHES = (64, 32, 16, 8, 4, 2, 1)`
  (`agent/skills/evaluate_vram_skill/batch_resolver.py:58`); the descending
  loop `for B in candidate_batches:` (`:155`) returns the first B clearing
  the VRAM + compute-intensity caps (`return B`, `:222-223`); a probe OOM at
  a larger B `continue`s to the next-smaller one (`:184-199`); if even B=1
  fails it **raises** (`:241-251`) — there is **no floor, no `max(…, 25)`,
  no minimum-batch gate, and no sub-25 admission filter** anywhere on the
  path. The only `25` is the legacy `_DEFAULT_INFERENCE_BATCH`
  (`core/inference_defaults.py:60`), consulted **only** as the `is None`
  fallback at `sandbox_executor.py:1543` — bypassed whenever the probe
  supplies a value (always, on a feasible check).
- The resolved sub-25 B flows unclamped into `active_params["inference_batch"]`
  (tuner :4695-4697) → the time gate (`:4725`, after :4696) → runtime
  (`:5031` → `sandbox_executor.py:1543`).
- So B ∈ {16, 8, 4, 2, 1} is genuinely reachable for a candidate reaching
  inference (a memory-heavy generated model whose larger candidates OOM /
  exceed the caps), and the time gate then prices its inference at the
  reachable batch. The false-admission direction is therefore **live** on
  the GPU probe path.
- **B=1 caveat (control-flow scope).** The CPU-only host also returns
  `inference_batch: 1` (`evaluate_vram_skill/wrapper.py:569-584`), and the
  ×2.7 branch fires on any `measured > 0` training warmup
  (`evaluate_time_skill/wrapper.py:706-754`, gated on `data_dir`, not
  device). But CPU-only is a degenerate "skip VRAM gate" fallback, and this
  audit did **not** positively confirm from source that a CPU-only run
  produces a training warmup and reaches this time-gate path in production.
  So the **~25× under-price at B=1 is recorded as a formula-level /
  reachable-batch worst case**, not as an observed live CPU time-gate
  admission. The live, source-confirmed under-price is the GPU sub-25 path
  (e.g. B=16 → ~1.56× real/forecast; B=8 → ~3×).

#### 0.R.11 The Gate must enter the ×2.7 path — and deterministically can

`inference_ms_source` is persisted end-to-end: wrapper breakdown
(:843) → tuner extra fields (:425) → `final_record["memory"]
["inference_ms_source"]` (:5653) — the Gate evidence can quote it
mechanically. Path-selection conditions (wrapper :745-756 + tuner
:1595-1622): the hint requires a PRIOR successful trial record in the
CURRENT iteration with `memory.inference_per_psd_seg_ms_measured > 0`;
the training warmup `measured` is produced in-gate when `data_dir` is
available. Therefore **the first trial attempt of a fresh iteration
deterministically takes `training_warmup_x2.7_fallback`** (no prior
trial record exists yet; warmup runs). The Gate is frozen accordingly
(§4): probed ≠ 25 AND the gated attempt's record shows
`inference_ms_source == "training_warmup_x2.7_fallback"`, with the
old/new effective batch and gate outcome quoted. A deterministic
pseudo test additionally pins the branch; the ONE real run proves
end-to-end reachability.

#### 0.R.12 Training-phase identity: hash, comparability and reuse are PROVEN batch-insensitive (outcome A)

Source proof:
- `planned_config_hash` hashes `{model_type, model_family,
  optimizer_type, seg_size, batch_size(TRAINING), runtime_flags}` —
  `inference_batch_size` is NOT an input
  (`gpu_measurement_identity.py:196-205`).
- Training-phase comparison iterates `COMPARABLE_FIELDS` =
  `(model_type, model_family, optimizer_type, seg_size, batch_size)`;
  `INFERENCE_COMPARABLE_FIELDS = ("inference_batch_size",)` is applied
  ONLY under `if phase == "inference"` (:79-98, :309-312).
- `inference_workload_hash` is a separate derived string
  (`_inference_workload_hash`, :219-232) with **ZERO consumers outside
  the identity module** (grep-proven) — persisted but unread.
- Measurement reuse: `MeasuredRequirementTable.from_measurements` is
  built per-request (`prephase_admission.py:225`); no cache keys on the
  inference fields; the RT3 observation store is a separate mechanism.

So changing 25→64 in a TRAINING-phase planned identity changes exactly
two currently-unread payload strings (`inference_batch_size`,
`inference_workload_hash`) and nothing else — hash, comparability and
reuse provably unchanged. **Outcome A.** One honest caveat for Q-G-3:
because those fields are unread today, the live value of threading the
hint is payload truthfulness alone. The alternative "add
`explicit=` API now, thread later" is REJECTED as design — an argument
with no caller is precisely the §E.3d.1 anti-pattern this ledger keeps
finding. The real choice is: thread the live hop now (proven safe;
one argument + pinning tests), or defer G3's live hop entirely and do
only the comment-truth fixes. Recommendation: thread now — the cost is
one argument, the safety is proven, and it removes the trap while the
audit knowledge is fresh.

---

## 1. Objective (restated from evidence)

Make the already-live probe-derived inference batch the **single
coherent authority on the agent path** — runtime (already done), the
wall-time forecast's one batch-sensitive path plus explicit both-sides
threading (G1+G2; the live inference-VRAM forecast is the structural
probe already, and the estimator's VRAM entry point is production-dead
— 0.R.2), and the measurement-identity payload (G3, 0.R.12) — and
close the stale A.7/A.9 migration with a contract test + comment truth
(G4; the agent-path fallback is unreachable by construction, 0.R.6,
so no new observability). Baselines and legacy scripts keep the
calibrated table, documented as intentional.

## 2. Non-goals

- No change to inference numerics, scoring, or the frozen TIDMAD
  metric; no change to `batch_resolver.py` search semantics.
- No change to S3 admission semantics (PR B) or admission ownership
  (O-C-2); `inference_batch_uncalibrated` stays observability-only.
- **No NEW planner-facing field, schema, or prompt exposure**, and no
  production-default changes inside the implementation commits — G2's
  behavior change on the agent path lands only with its parity evidence and
  explicit operator approval (Q-G-2). (Note: G2 does not add planner
  exposure, but correcting the time-gate price naturally changes *whether*
  the existing `skipped_time_risk` skip-feedback is produced — a plan
  wrongly skipped when B > 25 now runs, and a plan wrongly admitted when
  B < 25 is now correctly skipped. That existing feedback reaching the
  planner differently is the intended consequence of §0.R.10/§0.R.10a, not
  a new exposure surface.)
- No table deletion; no touching `run_comparison.py` baselines.
- No empirical throughput campaign design beyond the single bounded
  real-inference validation listed under the PR-level Gate (§4).

---

## 3. Commit plan

### Commit G1 — Forecast seam: explicit-batch override, default parity

#### 1. Goal
Give both forecast surfaces (`inference_skill/estimator.py`,
`evaluate_time_skill/wrapper.py`) an optional explicit
`inference_batch` input, with **byte-identical default behavior** when
it is absent. This is the inert seam; wiring is deliberately a separate
commit (G2) so the behavior change carries its own evidence and
approval, per the standing rule that production-default changes are
outside the implementation commits.

#### 2. Scope
- Files: `agent/skills/inference_skill/estimator.py` (both entry
  points), `agent/skills/evaluate_time_skill/wrapper.py` (:746 region);
  their unit tests.
- Non-goals: no caller passes the new argument yet; no schema change;
  no tuner change. `inference_batch_uncalibrated` computation unchanged
  (still "is the model registered", NOT "was a hint present" — the flag
  keeps its calibration meaning).
- Dependencies: none.

#### 3. Implementation plan
- [x] Inspect both estimator entry points' exact signatures and the
      breakdown dict shape before finalizing the argument name/threading
      (rule: no guessed interfaces). *(Done — both entry points and the
      wrapper's `run_skill` re-read in full before each edit.)*
- [x] Add optional `inference_batch: int | None = None` to
      `estimate_wall_time_seconds`; when provided, it replaces the
      VALUE of the existing `inference_batch` breakdown key. **NO new
      output key on ANY path (0.R.1)** — the authoritative batch is
      already recorded at `record_params["inference_batch"]` (:4697).
      `estimate_peak_bytes` is NOT given the argument (production-dead
      on the forecast path, 0.R.2) — its docstring gains one line
      stating that. *(Done — implemented via a new module-level
      `resolve_forecast_batch(explicit, model_type)` resolver:
      fail-closed (`bool`/non-int/≤0 → `ValueError`, no silent clamp);
      `None` → `inference_batch_for` exactly as before. A set-equality
      test pins that no breakdown key was added.)*
- [x] Same optional input for the time-skill wrapper's `inf_batch`
      (:746), threading through the `inference_ms` scaling (:749).
      *(Done — `run_skill` reads an optional `inference_batch` kwarg,
      resolves it through the same `resolve_forecast_batch` (inside the
      `try`, so an invalid value surfaces as the structured
      `status: "error"` return), uses it for the hint scaling AND
      passes the same value into `estimate_wall_time_seconds` — the
      0.R.3 both-sides coherence is wrapper-internal from G1 on; G2
      adds only the tuner→wrapper hop.)*
- [x] Unit tests per §4 below. *(9 estimator tests in
      `tests/unit/agent/inference_skill/test_estimator.py`
      (`TestResolveForecastBatch`, `TestG1ExplicitBatchSeam`) + 7
      wrapper tests in `tests/unit/agent/tune_ml_hyperparam_agent/`
      `test_evaluate_time_skill_g1_batch_seam.py`. Parity pins are
      full-dict `==` against HARDCODED pre-G1 algebra (rnn B=10 →
      25 000 steps; fallback B=25 → 10 000 steps at seg 16000 /
      400 PSDs), for a registered and an unregistered model.)*

#### 4. Validation plan
- Unit: with the argument absent, the returned estimate/breakdown is
  **deep-equal** to the pre-G1 output for a registered and an
  unregistered model (parity pin — trivially satisfiable now that no
  key is added); with the argument present, the breakdown's
  `inference_batch` equals the explicit value and the step count /
  wall-time follow the 0.R.3 algebra.
- Negative: explicit batch ≤ 0 rejected by validation with a clear
  error (no silent clamp).
- Backward-compat: C3b's existing test file passes unmodified in G1
  (the pin still holds — nothing passes a hint yet).
- No integration/Gate tests in G1 (inert seam).

#### 5. Acceptance criteria
- A parity test proves default-path deep-equality of the full breakdown
  dict (not just the batch field) for both a registered and an
  unregistered model_type.
- A test proves the explicit value is used verbatim when supplied and
  that `inference_batch_uncalibrated` is UNCHANGED by supplying it.
- Mutation: changing the override precedence (explicit vs table) is
  caught by a named test.

#### 6. Failure and edge cases
| Case | Behavior |
|---|---|
| Explicit batch ≤ 0 or non-int | Loud validation error (estimator returns its structured error path; never a silent fallback) |
| Explicit batch present AND model registered | Explicit wins — the hint is the batch that will run. **No new breakdown/output key**: the existing `breakdown.inference_batch` simply reports the value used; G1 adds no `inference_batch_source` field or any other schema change |
| Hint absent | Exactly today's behavior, proven by parity test |

#### 7. Verification commands and evidence
- [x] Targeted suite (2026-08-10): `pytest tests/unit/agent/inference_skill/
      tests/unit/core/test_inference_batch_absence_is_observability_only.py
      tests/unit/agent/tune_ml_hyperparam_agent/test_evaluate_time_skill.py
      tests/unit/agent/tune_ml_hyperparam_agent/test_inference_hint_path.py
      tests/unit/agent/tune_ml_hyperparam_agent/test_evaluate_time_skill_g1_batch_seam.py
      tests/unit/agent/tune_ml_hyperparam_agent/test_c8_timeeval_authority.py -q`
      → **116 passed in 1.24 s, rc=0** (rc read from pytest itself, log
      captured; identical result re-run after `ruff format`). *Deviation:
      the planned glob `tests/unit/agent/evaluate_time_skill*` matches no
      existing path — wrapper tests live under
      `tests/unit/agent/tune_ml_hyperparam_agent/` (existing convention),
      so the new file was placed there and the command lists the real
      wrapper test files.*
- [x] Targeted mutation evidence (3 attempted / 3 caught / 0 equivalent /
      0 invalid; each site count==1, `__pycache__` cleared per round,
      files restored from backups — NOT `git checkout`, which would have
      destroyed the uncommitted seam — and baseline re-run green,
      39 passed):
      1. estimator precedence reversal (`return explicit` →
         `return inference_batch_for(model_type)`): caught by the named
         `test_explicit_overrides_table_precedence` + 3 others.
      2. wrapper→estimator hop deleted (drop
         `inference_batch=explicit_inference_batch` at the estimator
         call): caught by `test_explicit_batch_reaches_both_sides_with_
         same_value` + `test_explicit_batch_reaches_real_estimator_
         breakdown`.
      3. scaling side ignores the hint (`resolve_forecast_batch(None,
         model_type)`): caught by the both-sides test (+ the invalid-
         value tests, which stop rejecting).
- [x] ruff check clean; `ruff format` applied (wrapping only) and
      `--check` clean on all four touched files. **pyright: NOT runnable
      on this host** — system Node is v10.19.0 and the pyright bundle
      fails to load (`SyntaxError: Unexpected token =`); no newer Node
      exists on the machine. Recorded per the environment-assumptions
      rule: pyright is a CI-only check for this PR; no local pyright
      claim is made.

#### 8. Commit boundary
- [x] Diff contains only the two forecast surfaces + tests (+ this
      ledger and the folder README status row); no tuner, no executor,
      no runtime_control changes.
- [x] ~~Show diff summary + staged list + test evidence, then commit.~~
      Superseded by the operator's Implementation Working Rules
      (2026-08-10): semantic commits are autonomous; the evidence is
      recorded above instead of shown at an operator stop.

---

### Commit G2 — Wire the probed batch into the time gate (agent path)

#### 0. Corrected understanding (implementation audit, 2026-08-10)

```text
Previous assumption (frozen design, §G1.2 "no caller passes the new
  argument yet" / §G2.3 "thread active_params.get('inference_batch')
  into the time-skill call"):
  the tuner needed a G2 code change to deliver the probed batch, and
  G1's wrapper seam would stay inert until then.

Audit evidence:
  _run_time_preflight has ALWAYS splatted **active_params into the
  skill kwargs (tuner :1168-1178, `**active_params` at :1171), and
  active_params["inference_batch"] is set at :4696 — before the gate
  fires at :4725. _run_skill (:2166-2176) forwards **params verbatim
  to the wrapper. The key was present-but-unread in the wrapper's
  kwargs the whole time. (§0.B row 3 knew the value was in
  active_params at gate time; the missed detail was only that the
  splat already transports it.)

Corrected understanding:
  the tuner→wrapper hop pre-exists. G1's wrapper consumption went
  LIVE on the agent path the moment it landed; G2 contains ZERO
  tuner code changes. G2 is the evidence-and-truth commit: the
  two-directional verdict-flip tests, the transport/reachability
  pins, the 0.R.4 negative pin, the C3b extension, the parity
  matrix, comment truth (the three "until G2"/"no caller" docstring
  claims corrected), and the skill/node .md sync.

Implementation consequence:
  no diff in nodes/; the G1 commit message was amended (pre-push,
  7cc6aef4) to state the immediate liveness instead of the false
  "no caller supplies the value yet" claim. The composite G1+G2
  end state is exactly the approved Q-G-2 change.

Validation consequence:
  the "delete-the-hop" reachability test targets the REAL hop (the
  **active_params splat / key presence), mutation-verified by
  stripping the key at the splat. Bounded deviation, recorded here;
  no operator stop — the behavior change itself is the
  operator-approved Q-G-2 change and nothing was pushed before its
  evidence landed.
```

#### 1. Goal
Make the time gate **price inference at the batch that will actually run**
(the real invariant — §0.R.10/§0.R.10a — not "a less-conservative
forecast"). Concretely: fix the one order-of-magnitude batch-sensitive
forecast path (`training_warmup_x2.7`), whose table=25 error is **two-sided**
(over-prices when the probed batch > 25 → wrongful `skipped_time_risk`;
under-prices when it is < 25 → wrongful admission), and replace the other
two paths' coincidental same-value use (both sides happening to call
`inference_batch_for`) with explicit same-value threading so their bounded
per-file residual stays bounded. This is the PR's one intended
production-behavior change on the agent path, isolated here with its own
parity evidence. **Lands only after Q-G-2 confirmation.**

#### 2. Scope
- Files: `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py`
  (the `_run_time_preflight` call seam, :4712 region — pass
  `active_params["inference_batch"]`, already set at :4696 before the
  gate fires); `evaluate_time_skill/wrapper.py` (consume it via G1's
  seam); tuner unit tests; the tuner node `.md` (doc-sync rule).
- Must remain unchanged: VRAM-gate behavior (it already probes); record
  schemas (`inference_batch` already lands in `record_params` :4697);
  every no-hint path (baselines, legacy scripts); retry/round/phase
  ordering (responsibility-oriented decomposition rule — this is an
  argument-threading change, not new branching in the orchestrator).
- Dependencies: G1.

#### 3. Implementation plan
- [x] Inspect `_run_time_preflight`'s signature and the wrapper's
      kwargs contract before finalizing (no guessed interfaces).
      *(Done — and this inspection produced the §G2.0 corrected
      understanding: the hop pre-exists via the `**active_params`
      splat.)*
- [x] Thread `active_params.get("inference_batch")` into the time-skill
      call; the wrapper uses it for its `inf_batch` (:746) AND passes
      the SAME value into `estimate_wall_time_seconds` via G1's seam —
      **never one side only** (0.R.3: one-sided threading breaks the two
      sides' same-batch coherence and re-introduces a probed/table ratio
      error into the measured path). A test pins the both-sides invariant.
      *(Satisfied with zero tuner diff — the splat already threads it
      (§G2.0); the wrapper's both-sides use landed in G1 and is pinned
      by the G1 both-sides test + mutations 2/3.)*
- [x] **Two-directional deterministic gate tests (0.R.10a; pseudo, no real
      run).** On the `training_warmup_x2.7` branch, with a fixed
      `total_ml` and a time budget chosen strictly between the old (B=25)
      and new (probed B) forecasts, assert the verdict FLIPS the correct
      way in BOTH directions:
      - **B > 25** (e.g. 64): old forecast `ceil(total_ml/25)` exceeds the
        budget → old REJECTS; new forecast `ceil(total_ml/64)` is under →
        new ACCEPTS.
      - **B < 25** (e.g. 16): old forecast is under the budget → old
        ACCEPTS; new forecast `ceil(total_ml/16)` exceeds it → new REJECTS.
      Deterministic unit/pseudo evidence — it needs no second real Gate.
      *(Done —
      `tests/unit/agent/tune_ml_hyperparam_agent/test_g2_time_gate_probed_batch.py::TestVerdictFlipsBothDirections`,
      unregistered model (old batch = fallback 25), warmup-measured
      training provenance so REJECT is real (§7.4). B=64 @ budget 14 min:
      old REJECTS (15.5 min) / new ACCEPTS (12.76 min); B=4 @ budget
      20 min: old ACCEPTS (15.5) / new REJECTS (39.1). Asserts
      `feasible`, `over_effective_budget`, the estimator's priced batch,
      and `inference_ms_source == "training_warmup_x2.7_fallback"`.
      B=4 chosen over the sketch's 16 for a wider margin; same 0.R.10a
      class.)*
- [x] Negative construction-pin test (0.R.4): a hint-less attempt
      following a hinted attempt delivers None to the wrapper —
      `active_params` is rebuilt per attempt at :4452, so stale leakage
      is impossible; the test makes that construction property durable.
      *(Done — `TestTunerTransport::test_hintless_active_params_delivers_no_batch`:
      a hint-less `active_params` delivers NO `inference_batch` key
      through `_run_time_preflight`, so the wrapper resolves the
      registry default exactly as pre-G.)*
- [x] Extend the C3b pin (§0.D): a new test asserting that ON THE HINT
      PATH the forecast batch equals the runtime batch (the restored
      invariant), alongside the existing no-hint pin.
      *(Done — `test_planning_and_runtime_agree_on_the_batch_for_a_hinted_model`
      in the C3b module: forecast prefers the hint verbatim and its
      no-hint fallback is the SAME function the executor falls back to;
      end-to-end transport equality delegated to the pseudo test below.)*
- [ ] **Per-builtin parity matrix (§E.3d.7 discipline, recorded in this
      doc):** for the six shipped model types, compare the probe-derived
      batch against the table entry; every difference explained (e.g.
      `transformer: 1` O(T²) vs probe outcome), never averaged away.
      **Hardware-local diagnostic on the lilab reference host only
      (PR F calibration boundary) — never a universal expected
      mapping**; cost bounded ≈10-20 min CPU total from PR F's measured
      probe costs (0.R.8); the resolver and the table do NOT change
      because of the matrix in PR G. Evidence recorded here before the
      commit is finalized.
- [x] Reachability evidence: a test that fails if the tuner stops
      passing the hint (deleting the hop breaks it — transport-contract
      discipline).
      *(Done, two layers: (1)
      `TestTunerTransport::test_probed_batch_reaches_time_skill_kwargs`
      pins the `_run_time_preflight` splat; (2)
      `tests/integration/workflows/test_g2_forecast_runtime_batch_pseudo.py`
      runs ONE dual-mode pseudo tuner iteration (the K.9 choreography
      with BOTH time budgets enabled) with pass-through shims on the
      real time/inference wrappers, asserting per attempt:
      forecast batch is not None, forecast batch == runtime batch
      (probed 32 on this host — not the table, not the fallback), and
      the record's `params["inference_batch"]` carries the same value.
      The record schema has no forecast-batch field and G2 may not add
      one (§2 non-goals), so equality is asserted at the skill
      boundaries — bounded deviation from the sketch's "on the record"
      wording. TEST-BUG deviation found and fixed during bring-up: the
      forced-formal round 2 reads `formal_time_budget_minutes`, which
      the first draft left None, silently skipping the second gate
      firing — the input now enables both budgets.)*

#### 4. Validation plan
- Unit (tuner, mocked skills): the time skill receives the same batch
  the inference skill will receive; absent hint → today's behavior.
- Pseudo integration: one dual-mode tuner iteration asserting
  forecast-batch == runtime-batch on the record.
- Negative: resource_check missing `inference_batch` (infeasible/error
  shapes) → time gate behaves exactly as today (no crash, no hint).
- Backward-compat: no-hint paths byte-identical (G1 parity test
  re-used); baselines untouched by construction (no code path change).
- Real-training Gate: NOT part of G2 — the single bounded real
  validation is PR-level (§4) and operator-approved separately.

#### 5. Acceptance criteria
- The extended C3b-family test proves forecast-batch == runtime-batch
  on the hint path AND the original no-hint pin still passes.
- The parity matrix table in this doc is filled with actual probe vs
  table values for all six builtins, each difference explained.
- A deleted-hop test (hint not forwarded) fails — reachability proven.
- `inference_batch_uncalibrated` is still never a predicate (existing
  guard test passes unmodified).

#### 6. Failure and edge cases
| Case | Behavior |
|---|---|
| Resource check infeasible / error / schema-violation | Never reaches the time gate or inference (0.R.6: skip-record + continue, raise, or retry) — no no-hint time-gate case exists on the agent path |
| CPU-only host | Hint present by construction (`inference_batch: 1`, wrapper :582) |
| Hint present but time budget None | Gate skipped as today; hint unused, no record change |
| Probed batch differs wildly from table on a builtin | Legal; the parity matrix explains it; no clamping to the table |

#### 7. Verification commands and evidence
- [x] Targeted tuner + skill tests (2026-08-10):
      `test_g2_time_gate_probed_batch.py` → 4 passed (1.11 s);
      `test_g2_forecast_runtime_batch_pseudo.py` → 1 passed (37.4 s);
      C3b module incl. the new hinted-model pin → green in the same
      run (log `g2_pseudo.log`: 9 passed alongside the pre-fix pseudo
      failure; post-fix rerun 1 passed). All rc read from pytest.
- [x] Parity matrix evidence (2026-08-10, hardware-local diagnostic —
      lilab reference host, RTX 5090, `usable_cap` 25.1 GB of 31.3 GB,
      torch 2.10.0+cu128; paper-spec baseline configs; the SAME
      production resolver `resolve_inference_batch` with default
      candidates/budgets; ~2.5 min total, well under the 0.R.8 bound;
      resolver and table unchanged):

      | model | seg | params | table | probed | note |
      |---|---|---|---|---|---|
      | punet | 40000 | 6.76 M | 25 | **16** | 14.5 s |
      | wavenet | 40000 | 303 K | 25 | **16** | 42.2 s |
      | fcnet | 40000 | 323 M | 25 | **16** | 4.0 s |
      | rnn | 40000 | 1.97 M | 10 | **16** | 56.8 s |
      | transformer | 20000 | — | 1 | **crash at B=64** (F-A3) | see below |
      | gated_fno | 40000 | 61.5 M | 25 (fallback — NO table entry) | **16** | 16.7 s |

      Differences explained, per row:
      - **All completed probes resolve 16 < table 25** (and > rnn's 10):
        at seg 40 000 the resolver's conservative
        `forward_output_bytes_sum` bound prices B=32 over the 25.1 GB
        cap for every one of these architectures; 16 clears it. The
        table values are legacy hand calibrations against a different
        bound. Probed ≠ table is therefore COMMON even on builtins —
        the coherence gap G2 closes is not a generated-models-only
        phenomenon on this host.
      - **transformer**: the default descending search begins at B=64,
        whose single attention matrix at seg 20 000 is
        64 × 2 × 20 000² × 4 B ≈ 204.8 GB; the CPU allocator raises
        ENOMEM, torchinfo re-wraps it as a generic
        `RuntimeError("Failed to run torchinfo…")`, and
        `is_memory_exception` does not recognize the laundered form, so
        the resolver re-raises instead of stepping down — **PR F's
        recorded F-A3 finding reproduced by the matrix**, the
        2026-07-31 incident class. A bounded host-safe follow-up probe
        (candidates `(4,2,1)`, ≤ 12.8 GB transient) shows it WOULD
        resolve **4** (table: 1). Not fixed here — F-A3 remains a
        recorded follow-up outside PR G scope (0.R.8: the matrix
        changes nothing).
      - **gated_fno has no table entry at all** — its "table" value is
        the K.2.5-8 silent fallback 25, confirming §E.3b's finding on a
        SHIPPED builtin, not just generated models.

      Hardware-local only (PR F calibration boundary): these probed
      values are properties of this host's cap and allocator, never a
      universal expected mapping. Evidence log:
      scratchpad `g2_parity_matrix.log`.
- [x] Mutations (2/2 attempted, 2/2 caught, site count==1 each,
      pycache cleared, backup-restore — never `git checkout` — baseline
      re-run 13 passed):
      - **A. forecast reads table despite hint** (wrapper's
        `kwargs.get("inference_batch")` → `None`): caught by BOTH
        verdict-flip tests. The pseudo test correctly still passes —
        it pins TRANSPORT at the wrapper boundary while the flip tests
        pin CONSUMPTION; the two families are complementary, neither
        subsumes the other.
      - **B. tuner hop deleted** (`**active_params` splat strips
        `inference_batch` in `_run_time_preflight`): caught by the
        transport test AND the pseudo coherence test.

#### 8. Commit boundary
- [x] Diff = wrapper/estimator comment truth + tests + skill `.md`s +
      tuner node `.md` + this ledger; ZERO tuner/executor/
      runtime_control code changes (§G2.0 — the hop pre-exists).
- [x] ~~Show diff summary + evidence + deviations, then commit.~~
      Superseded by the Implementation Working Rules (autonomous
      semantic commits); evidence recorded above.

---

### Commit G3 — Measurement-identity alignment and stale-canonical-comment fix

#### 1. Goal
NARROWED per 0.R.5. The live path requests training-phase measurements
only, where the batch is inert for comparison — so G3 does NOT create a
live `measurement_batch == runtime_batch` equality and must not claim
one. What it does: (a) the planned-identity PAYLOAD stops recording a
batch that is not the one production would run (the hint is already
in-scope at the :4917 call site — a one-argument preference, no
reordering); (b) the latent trap for a future inference-phase
measurement caller is closed; (c) the stale "canonical source"
comments stop claiming table==runtime.

#### 2. Scope
- Files: `core/runtime_control/gpu_measurement_identity.py`
  (`resolve_inference_batch` :165-176 and the field comments :85-130),
  `gpu_measurement_spec.py` comment (:130,:217), the tuner's pre-phase
  call site (:760 — pass the probed hint when available); unit tests.
- Must remain unchanged: phase-aware comparison semantics
  (`INFERENCE_COMPARABLE_FIELDS`), training-phase identity fields, the
  worker protocol, admission (O-C-2: admission is NOT PR G's).
- Dependencies: G1 (none technically, but sequenced after G2 so the
  hint's production meaning is already established).

#### 3. Implementation plan
(Rev 3: outcome A proven in 0.R.12 — training hash/comparability/reuse
are batch-insensitive; the two changed payload strings are currently
unread. The "add `explicit=` API without a caller" alternative is
REJECTED as the §E.3d.1 anti-pattern. G3 = thread the live hop now +
comment truth; severable if the operator prefers deferral.)
- [ ] `resolve_inference_batch(model_type, explicit=None)`: prefer the
      explicit probed batch when provided; table fallback otherwise —
      landed TOGETHER with its live caller (next step), never as an
      uncalled parameter.
- [ ] Tuner pre-phase site passes `active_params.get("inference_batch")`
      — ordering already proven (0.R.5): the spec is built at :4917,
      after the hint capture at :4696, and `active_params` is already
      an argument of the helper. No phase reordering.
- [ ] Correct the stale comments (identity :169-171, spec :130/:217,
      executor :1518-1524's "A.9 will remove" narrative → point at G4's
      actual disposition).
- [ ] Unit tests per §4.

#### 4. Validation plan
- Unit: explicit beats table; absent explicit == today (parity).
- **Pin of 0.R.12:** a test proving `planned_config_hash` and
  training-phase `compare_identities` are UNCHANGED when the
  inference batch payload changes 25→64 (the property that makes G3
  safe), and that `inference_workload_hash` changes with the batch.
- Negative: explicit ≤ 0 rejected loudly.
- Backward-compat: all existing identity/spec tests pass unmodified
  except where they pin the stale comment text.
- No Gate test (comments + latent-path alignment; the live path is G2's).

#### 5. Acceptance criteria
- A test proves the planned-identity PAYLOAD carries the hint when one
  exists and the table value only when none does — stated as payload
  truth, NOT as a live measurement-path equality (0.R.5).
- No remaining source comment claims `inference_batch_for` is "the same
  source `execute_inference` uses" — verified by grep, recorded here.

#### 6. Failure and edge cases
| Case | Behavior |
|---|---|
| Measurement requested before any preflight ran | Table fallback, recorded as such in the identity (no fabricated hint) |
| Hint present for a training-phase spec | **Reflected in the recorded planned-identity payload** (`inference_batch_size`, `inference_workload_hash` — the payload-truth fix), but **inert to training semantics**: `planned_config_hash`, training-phase comparability (`COMPARABLE_FIELDS`), the worker, and cache/reuse are all batch-insensitive (0.R.12). Not the same as "ignored exactly as today" — the payload value changes 25→probed; only its downstream effect is nil |

#### 7. Verification commands and evidence
- [ ] `pytest tests/unit/core/ -k "identity or measurement_spec" -q` — **to record**
- [ ] Stale-comment grep proof — **to record**

#### 8. Commit boundary
- [ ] Diff = identity/spec + tuner one-argument threading + tests +
      comment corrections; nothing else.
- [ ] Show diff summary + evidence, then commit.

---

### Commit G4 — Fallback contract and the A.9 disposition

#### 1. Goal
NARROWED per 0.R.6: the agent-path fallback is UNREACHABLE by
construction (every route to inference carries a hint, incl. the
CPU-mode `"inference_batch": 1` return), so **no new production
observability is added for a path that cannot occur**. G4 closes the
A.7→A.9 migration honestly with: (a) a CONTRACT TEST pinning "every
feasible/CPU-mode resource_check carries `inference_batch: int ≥ 1`" —
the property that makes the fallback unreachable, made durable and
loud at test time; (b) comment/docstring truth (the executor's "A.9
will remove the fallback" narrative and the `inference_defaults.py`
consumer census per §0.B/0.R.2).

#### 2. Scope
- Files: `core/sandbox_executor.py` (comment truth only — NO behavior
  or record change), `core/inference_defaults.py` (docstring census),
  `agent/skills/evaluate_vram_skill/wrapper.py` (no code change — its
  return contract is what the new test pins), relevant `.md` docs
  (doc-sync rule); tests.
- Must remain unchanged: ALL runtime behavior (this commit is tests +
  comments/docs only); the fallback VALUE; baselines; the
  `inference_batch_uncalibrated` flag's meaning.
- Dependencies: G2 (so "agent path" has its final meaning).

#### 3. Implementation plan
- [ ] Contract test: every feasible/CPU-mode wrapper return shape
      carries `inference_batch: int ≥ 1` (parametrized over the return
      sites found in 0.R.6; fails if a new return path omits it).
- [ ] Update `inference_defaults.py` docstring + executor comments to
      the post-G4 truth (who legitimately consults the table; the A.9
      promise replaced by the tested contract).
- [ ] Record in this doc that the k9 "Feasible"-stdout failure is the
      isolated-preflight print relocation (observation only — a test
      fix belongs to its own maintenance change, not PR G).

#### 4. Validation plan
- Unit: the contract test over every feasible/CPU-mode return shape.
- Mutation: removing `inference_batch` from any feasible return site is
  caught.
- Backward-compat: zero runtime diff in this commit (tests + comments
  + docs only) — provable by an empty non-test/non-doc diff.

#### 5. Acceptance criteria
- The contract test fails when any feasible/CPU-mode return path drops
  `inference_batch` — the unreachability property is pinned.
- Docstring census in `inference_defaults.py` matches §0.B/0.R.2.
- The commit's non-test/non-doc diff contains only comment lines
  (mechanically shown at the commit boundary).

#### 6. Failure and edge cases
| Case | Behavior |
|---|---|
| Fallback on a no-record path (baseline/legacy script) | Intentional and documented; no change |
| A future wrapper return path omits the hint | The contract test fails — the regression is caught at test time, before production |

#### 7. Verification commands and evidence
- [ ] Targeted executor tests — **to record**
- [ ] Doc-sync check (node/skill `.md`s quote the merged flags/defaults)
      — **to record**

#### 8. Commit boundary
- [ ] Diff = contract test + comment/docstring truth + docs — zero
      runtime diff, mechanically shown at the boundary.
- [ ] Show diff summary + evidence, then commit.

---

## 4. PR-level acceptance and merge criteria

1. **Zero score/metric change**; `inference_batch_uncalibrated` still
   observability-only (existing guard tests unmodified and green).
2. **Coherence invariant proven (restated per 0.R.5):** on the live
   agent path, **forecast batch == runtime batch** (both wrapper and
   estimator sides, delete-the-hop reachability test per hop). The
   measurement-identity leg is a PAYLOAD-truth + latent-trap-closure
   claim only — no live inference-phase measurement exists to equate,
   and this PR does not pretend otherwise.
3. **Parity proven:** every no-hint path byte-identical to today
   (deep-equal breakdowns; baselines untouched); per-builtin parity
   matrix recorded with every probe-vs-table difference explained.
4. **The table remains** for its documented consumers; its docstring
   census matches the audit (§0.B).
5. **Bounded real validation (PR-level Gate, operator-approved
   separately, cold-start per the standing rule):** ONE bounded real
   run on ONE generated model satisfying BOTH (0.R.7 + 0.R.11):
   **probe-derived batch ≠ 25** AND the gated attempt's record shows
   **`inference_ms_source == "training_warmup_x2.7_fallback"`** — the
   one path G2 materially changes; deterministically reachable as the
   first trial attempt of a fresh iteration. Evidence quotes
   mechanically: forecast source, old effective batch (25), new
   explicit batch (probed), runtime batch (same), and the time-gate
   outcome; plus the frozen scorer accepting the output, scorer/metric
   implementation untouched. **Deterministic pseudo tests** pin the branch
   AND the two-sided verdict flip (0.R.10a): one `B > 25` case (old rejects
   / corrected accepts) and one `B < 25` case (old accepts / corrected
   rejects), each with the time budget set between the old and new
   forecasts. The **one** real run proves end-to-end reachability; it need
   satisfy only `probed batch ≠ 25` AND
   `inference_ms_source == "training_warmup_x2.7_fallback"` — a single
   generated model, either direction, suffices (no second real Gate). No
   throughput campaign. All timings hardware-local (PR F calibration
   boundary).
6. Full checker set per §E.3d.12 at the final heads; CI green on the
   exact final HEAD.

## Operator decisions (rev 3 — final form for freeze)

### Q-G-1 — Scope restatement — **APPROVED (operator, rev-2 review)**
The ledger's "remove the name-keyed fallback / name table removed from
the path" is superseded by: *the table is never consulted on the agent
production path when a probe hint exists (a property that already holds
at runtime and is pinned by G4's contract test); its remaining
consumers (baselines, legacy scripts, proposer advisory, no-hint
fallback) are documented.*

### Q-G-2 — The one production-behavior change (G2) — **APPROVED / FROZEN (rev 3 final reconciliation; all conditions discharged)**
Rev-2 discharged the call-graph and state-lifetime conditions (0.R.2,
0.R.4). Rev 3 final discharges the rest:
1. *Exact per-file ceil bound* (0.R.9): the measured/static paths carry
   only a **bounded, always-downward** per-file ceil residual —
   `Σᵢ ceil(mlᵢ/B) − ceil(Σᵢ mlᵢ/B) ≤ n_files − 1` steps (≤ 19); as a
   relative error ≤ 2.4 % at the default trial, ≈ 1.08 % at the default
   seg 40 000, and a supported-grid worst case ≈ 21.9 % at an atypical
   (P=1, seg 50 000, B=64). This is a **second-order** term beside the ×2.7
   path's `ceil(total_ml/25)/ceil(total_ml/B)` **factor**. The
   "≤2.4 % / smallest realistic set / exactly cancels" phrasings are
   corrected in place.
2. *Two-sided pricing error* (0.R.10, 0.R.10a): the ×2.7 forecast at
   table=25 is **NOT always conservative**. A probed batch < 25 is
   reachable (candidate set `(64,…,1)`, no floor — 0.R.10a), so the old
   forecast can also UNDER-price and **wrongly admit** a plan whose real
   inference exceeds the budget, as well as over-price and wrongly skip one.
   G2's invariant is therefore **"the time gate prices inference at the
   batch that will actually run"**, correcting BOTH directions — not merely
   making the forecast less conservative. Hypothesis GENERATION is
   untouched; no score/metric change.
G2 threads BOTH forecast sides with one value; both-directions pinned by
deterministic pseudo tests (0.R.10a) and the one real Gate; parity matrix
hardware-local and cost-bounded (0.R.8). **Freezes for implementation.**

### Q-G-3 — Identity alignment (G3) — **APPROVED / FROZEN — Option A (operator, rev 3 final)**
0.R.12 proves from source: `planned_config_hash` excludes the inference
batch; training-phase comparability excludes it; `inference_workload_-
hash` has zero consumers; no cache/reuse keys on it. Changing 25→probed
alters exactly two currently-unread payload strings. The "API without a
caller" middle option is rejected as the §E.3d.1 anti-pattern.
**Operator decision — Option A (approved):** thread the already-in-scope
probed batch into the live planned-identity payload now — one argument,
proven safe by 0.R.12 (no change to training hash, comparability, worker,
cache/admission), pinned by the hash/comparability-unchanged test, and it
removes the latent trap of a stale `25` sitting in the recorded payload.
The deferred alternative (comment-truth fixes only, live hop postponed to
the future inference-phase-measurement PR) is retired: Option A is one
small proven-safe step and closes the payload-truth defect now.

### Q-G-4 — A.9 disposition — **APPROVED in the narrowed form (operator, rev-2 review)**
No new production observability; G4 = contract test pinning "every
feasible/CPU-mode resource_check carries `inference_batch: int ≥ 1`" +
comment/docstring truth, zero runtime diff. A.9's "remove the
fallback" is formally retired in favor of "pin the contract that makes
it unreachable".

### Q-G-5 — Validation criterion — **APPROVED (operator, rev-2 review)**
No raw byte-identity across a legitimate batch change. Frozen criteria:
no-hint parity (deep-equal breakdowns; zero behavior change off the
agent path) + same-authority coherence (forecast == runtime) + frozen
scorer/metric untouched. The Gate case must satisfy probed ≠ 25 AND
`inference_ms_source == "training_warmup_x2.7_fallback"` (0.R.7,
0.R.11).

## V21 review fields

```text
Metric-frozen proof:      no scoring surface touched; guard tests
                          unmodified; frozen TIDMAD formula untouched
Name-keyed dependency
added:                    none — PR G REDUCES name-keyed reliance; the
                          table's remaining consumers are enumerated
                          and documented (§0.B census)
Transport contract:       two LIVE hops (time-gate forecast, runtime)
                          each carry a delete-the-hop reachability
                          test; the identity hop is payload-truth +
                          latent-trap closure (0.R.12), pinned by the
                          hash/comparability-unchanged test, not
                          claimed as a live measurement hop
Subprocess evidence:      runtime batch already crosses the subprocess
                          boundary today (:1543); G-commits add no new
                          boundary
Acceptance evidence:      parity matrix + coherence invariant + one
                          bounded operator-approved real inference
```

---

## Implementation status (live — updated as work proceeds)

**IMPLEMENTATION IN PROGRESS** (started 2026-08-10).

```text
branch   feat/pr-g-capability-derived-inference-batch
base     master @ 51bc3a7a (the rev-3 design commit)
HEAD     f48c1dee (design freeze) + G1 (7cc6aef4, message amended
         pre-push with the §G2.0 correction) + G2
G1       DONE — both seams + 16 tests + 3/3 mutations caught (§G1.7)
G2       DONE — zero tuner code change needed (§G2.0: the
         **active_params hop pre-exists); evidence = 2-direction
         verdict flips, transport + 0.R.4 pins, C3b extension,
         pseudo coherence iteration, parity matrix, 2/2 mutations,
         comment truth, skill/node .md sync
G3-G4    not started (G3 next, Option A)
PR       none opened yet
Gate     not run
jobs     no background jobs
```

All operator questions are discharged: Q-G-1 / Q-G-4 / Q-G-5 approved
(rev-2); Q-G-2 approved (rev-3, both conditions — the two-sided pricing
error and the bounded per-file ceil residual — closed by source audit);
Q-G-3 approved — Option A (thread the probed batch into the live
planned-identity payload, proven inert to training hash / comparability
/ worker / reuse by 0.R.12). The sequence is G1 → G2 (evidence
checkpoint) → G3 (Option A) → G4 → PR-level validation.

**Workflow supersession (operator directive, 2026-08-10):** the freeze
text's closing sentence ("Every commit stops to show its diff summary
… before committing") is superseded by the operator's Implementation
Working Rules: semantic commits are AUTONOMOUS; the evidence that would
have been shown at each stop is recorded in this ledger instead, and
implementation continues without operator checkpoints until PR G is
READY FOR OPERATOR REVIEW (PR opened, CI green on the exact final
HEAD). G2's evidence checkpoint is an EVIDENCE checkpoint, not an
operator stop, unless it materially contradicts the frozen design.
DO NOT MERGE — merge authority remains the operator's.

### Session-recovery record (2026-08-10, session 2)

- A stale PR-F-era durable handoff (written at master `c1925586`,
  clean tree) was injected at session start; its own guard flagged the
  HEAD/fingerprint mismatch. It was REJECTED in favor of repository
  truth per its recovery procedure. Repository evidence re-derived:
  branch `feat/pr-g-capability-derived-inference-batch` @ `f48c1dee`
  (1 commit ahead of master = the design freeze), one uncommitted
  file: `agent/skills/inference_skill/estimator.py` (+41/−1).
- Three parallel read-only audit agents re-established project state
  (docs/ledger, source tree, last 20 PRs). Load-bearing findings,
  verified against source by the main agent:
  - The uncommitted estimator diff implements the G1 seam exactly as
    designed: `resolve_forecast_batch(explicit, model_type)`
    (fail-closed; rejects `bool`/non-int/≤0), the optional
    `inference_batch: int | None = None` parameter on
    `estimate_wall_time_seconds` (no new output key;
    `inference_batch_uncalibrated` semantics untouched), and the
    `estimate_peak_bytes` production-dead docstring note (0.R.2).
  - The wrapper's own `inf_batch = inference_batch_for(model_type)`
    at `evaluate_time_skill/wrapper.py:746` is the second G1 surface
    (frozen scope §G1.2) — initially misread in-session as G2 work;
    corrected by the operator and confirmed against §G1 before any
    edit. G1 is PARTIAL until the wrapper seam + tests land.
  - `docs/design/v21_priorities/README.md` tracked PR E as
    "in-progress" during implementation (`b8ea7b50`), so it IS an
    in-progress status surface — its PR G row is updated now.
    `v21_priorities.md` follows the post-merge convention (PR F
    STATUS landed with/after the merge) and is deliberately NOT
    updated until PR G merges.

### G1 implementation record (COMPLETE — evidence in §G1.3/§G1.7)

- `agent/skills/inference_skill/estimator.py` — `resolve_forecast_batch`
  resolver + `inference_batch` parameter on `estimate_wall_time_seconds`
  + `estimate_peak_bytes` production-dead note (0.R.2).
- `agent/skills/evaluate_time_skill/wrapper.py` — optional
  `inference_batch` kwarg on `run_skill`; resolved through the same
  fail-closed `resolve_forecast_batch`; used for the `:749`
  `inference_ms` hint scaling AND passed into
  `estimate_wall_time_seconds` so the two sides cannot diverge once a
  caller supplies the hint (0.R.3). Invalid values surface through the
  wrapper's existing structured `status: "error"` path (the resolve
  happens inside the `try`).
- 16 new tests (9 estimator + 7 wrapper), 116-test targeted suite green,
  3/3 mutations caught. Bounded deviations recorded in §G1.7: test
  location (no `tests/unit/agent/evaluate_time_skill*` path exists) and
  pyright being CI-only on this host (Node v10.19.0). One clarification
  vs the §G1.6 failure table: the *estimator* entry point rejects an
  invalid override by raising `ValueError` (it has no structured error
  return of its own); the structured error path named by the table is
  the skill surface — the wrapper catches and returns
  `status: "error"`. Both are pinned by tests.
