# PR G — Capability-derived inference batch

**Status: DESIGN DRAFT rev 2 (2026-08-10) — awaiting operator review.
No implementation.** Rev 1's fresh audit found the capability-derived
mechanism **already live on the agent runtime path**. Rev 2 (operator-
directed read-only source audit, §0.R) resolves eight pre-implementation
questions and MATERIALLY narrows the scope again: the forecast
divergence is confined to ONE of three forecast paths (the batch cancels
exactly in the other two), the agent-path executor fallback is
unreachable by construction, stale-hint leakage is impossible, and the
measurement-identity fix is a one-line preference of a value already
in scope. Operator stances: Q-G-1 approved in principle, Q-G-5
approved in principle, Q-G-2 conditional (conditions now discharged by
§0.R — awaiting confirmation), Q-G-3/Q-G-4 revised and resubmitted.

| | |
|---|---|
| Plan section | `docs/design/v21_priorities.md` — PR G section + P5 + §E.3d (binding, incl. §E.3d.11-12) + §E.4 |
| Gate | **NOT a V21 launch blocker.** Throughput/forecast coherence only — no score, no hypothesis reachability |
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
| 1 | `core/sandbox_executor.py:1543` | **Fallback only** — used iff `inference_batch is None`; comment says "A.9 will remove the fallback once every caller has been migrated" (migration never completed) | G4: keep, observe loudly on agent paths (Q-G-4) |
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

> **Rev-2 correction (0.R.3):** the divergence is confined to the
> `training_warmup_x2.7` fallback path; the measured-hint and static
> paths are batch-invariant by exact cancellation. The gap is real but
> smaller than rev 1 claimed, and always in the conservative
> (over-estimate) direction.

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

No table-based live forecast consumer is left behind: after G2 the only
live consumer is the proposer's batch-invariant advisory estimate.

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

**The decisive algebra:** in the measured-hint path,
`seconds = (total_ml/inf_batch) × (hint × inf_batch / ml_per_psd)/1000
= n_psd × hint / 1000` — **`inf_batch` cancels exactly**, PROVIDED the
wrapper's `inf_batch` (:746) equals the estimator's internal one
(:240). Today both call `inference_batch_for` → identical → exact
cancellation. In the static path
(`_static_inference_ms_per_step ∝ inf_batch`, steps ∝ 1/inf_batch) the
batch also cancels. **Only the middle fallback path**
(`training_warmup_x2.7`: ms/step from a training measurement,
batch-independent; steps ∝ 1/inf_batch) is batch-sensitive:
`seconds ∝ 1/inf_batch`.

**Previous assumption** (rev 1): the time forecast diverges from
runtime for every model where probed ≠ table.
**Corrected understanding:** the divergence is REAL but confined to the
×2.7 fallback path (first iteration / OOM-killed trial / degenerate
sidecar — exactly generated models' early rounds), where table=25 vs
probed=64 OVERESTIMATES inference wall time ×2.56 (conservative
direction: wrongly rejects on time, never admits). The measured-hint
and static paths are already batch-correct via cancellation.
**Two G2 consequences:** (1) the fix is still justified — it corrects
the one wrong path and replaces accidental cancellation with explicit
same-value threading; (2) **G2 MUST supply the SAME explicit batch to
both the wrapper (:746) and the estimator (:240)** — changing one side
only would BREAK the measured path's cancellation and corrupt the
currently-correct forecast by the probed/table ratio. A test pins the
both-sides invariant.

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

---

## 1. Objective (restated from evidence)

Make the already-live probe-derived inference batch the **single
coherent authority on the agent path** — runtime (already done),
wall-time/VRAM forecast (G1+G2), and measurement identity (G3) — and
close the stale A.7/A.9 migration with loud observability instead of
silent fallback (G4). Baselines and legacy scripts keep the calibrated
table, documented as intentional.

## 2. Non-goals

- No change to inference numerics, scoring, or the frozen TIDMAD
  metric; no change to `batch_resolver.py` search semantics.
- No change to S3 admission semantics (PR B) or admission ownership
  (O-C-2); `inference_batch_uncalibrated` stays observability-only.
- No planner exposure and no production-default changes inside the
  implementation commits — G2's behavior change on the agent path lands
  only with its parity evidence and explicit operator approval (Q-G-2).
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
- [ ] Inspect both estimator entry points' exact signatures and the
      breakdown dict shape before finalizing the argument name/threading
      (rule: no guessed interfaces).
- [ ] Add optional `inference_batch: int | None = None` to
      `estimate_wall_time_seconds`; when provided, it replaces the
      VALUE of the existing `inference_batch` breakdown key. **NO new
      output key on ANY path (0.R.1)** — the authoritative batch is
      already recorded at `record_params["inference_batch"]` (:4697).
      `estimate_peak_bytes` is NOT given the argument (production-dead
      on the forecast path, 0.R.2) — its docstring gains one line
      stating that.
- [ ] Same optional input for the time-skill wrapper's `inf_batch`
      (:746), threading through the `inference_ms` scaling (:749).
- [ ] Unit tests per §4 below.

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
| Explicit batch present AND model registered | Explicit wins; source recorded — the hint is the batch that will run |
| Hint absent | Exactly today's behavior, proven by parity test |

#### 7. Verification commands and evidence
- [ ] `pytest tests/unit/agent/inference_skill/ tests/unit/core/test_inference_batch_absence_is_observability_only.py tests/unit/agent/evaluate_time_skill* -q` — counts/wall time **to record**
- [ ] Targeted mutation evidence — **to record**
- [ ] ruff + format + pyright on touched files — **to record**

#### 8. Commit boundary
- [ ] Diff contains only the two forecast surfaces + tests; no tuner,
      no executor, no runtime_control changes.
- [ ] Show diff summary + staged list + test evidence, then commit.

---

### Commit G2 — Wire the probed batch into the time gate (agent path)

#### 1. Goal
Close the live coherence gap as CORRECTED by 0.R.3: fix the one
batch-sensitive forecast path (`training_warmup_x2.7`) and replace the
other two paths' accidental cancellation (both sides happening to call
`inference_batch_for`) with explicit same-value threading. This is the
PR's one intended production-behavior change on the agent path,
isolated here with its own parity evidence. **Lands only after Q-G-2
confirmation.**

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
- [ ] Inspect `_run_time_preflight`'s signature and the wrapper's
      kwargs contract before finalizing (no guessed interfaces).
- [ ] Thread `active_params.get("inference_batch")` into the time-skill
      call; the wrapper uses it for its `inf_batch` (:746) AND passes
      the SAME value into `estimate_wall_time_seconds` via G1's seam —
      **never one side only** (0.R.3: one-sided threading breaks the
      measured path's exact cancellation). A test pins the both-sides
      invariant.
- [ ] Negative construction-pin test (0.R.4): a hint-less attempt
      following a hinted attempt delivers None to the wrapper —
      `active_params` is rebuilt per attempt at :4452, so stale leakage
      is impossible; the test makes that construction property durable.
- [ ] Extend the C3b pin (§0.D): a new test asserting that ON THE HINT
      PATH the forecast batch equals the runtime batch (the restored
      invariant), alongside the existing no-hint pin.
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
- [ ] Reachability evidence: a test that fails if the tuner stops
      passing the hint (deleting the hop breaks it — transport-contract
      discipline).

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
| VRAM gate infeasible/skipped → no hint | Time gate runs at table batch exactly as today (documented fallback, observability records it — G4) |
| Hint present but time budget None | Gate skipped as today; hint unused, no record change |
| Probed batch differs wildly from table on a builtin | Legal; the parity matrix explains it; no clamping to the table |

#### 7. Verification commands and evidence
- [ ] Targeted tuner + skill tests — counts/wall time **to record**
- [ ] Parity matrix evidence — **to record in this doc**
- [ ] Mutation: forecast reads table despite hint → caught — **to record**

#### 8. Commit boundary
- [ ] Diff = tuner seam + wrapper consumption + tests + node `.md`;
      no estimator internals beyond G1's seam, no runtime_control.
- [ ] Show diff summary + evidence + deviations, then commit.

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
- [ ] Inspect every `resolve_inference_batch` caller and the worker's
      inference-phase path (`gpu_measurement_worker_main.py:270,506`)
      before finalizing — today the tuner requests training-phase
      measurements only (:774,:4961,:5000); confirm nothing else
      constructs an inference-phase spec.
- [ ] `resolve_inference_batch(model_type, explicit=None)`: prefer the
      explicit probed batch when provided; table fallback otherwise.
- [ ] Tuner pre-phase site passes `active_params.get("inference_batch")`
      — ordering already proven (0.R.5): the spec is built at :4917,
      after the hint capture at :4696, and `active_params` is already
      an argument of the helper. No phase reordering.
- [ ] Correct the stale comments (identity :169-171, spec :130/:217,
      executor :1518-1524's "A.9 will remove" narrative → point at G4's
      actual disposition).
- [ ] Unit tests per §4.

#### 4. Validation plan
- Unit: explicit beats table; absent explicit == today (parity);
  identity hash changes iff the batch changes.
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
| Hint present for a training-phase spec | Ignored exactly as today (schema: `None` for training-phase) |

#### 7. Verification commands and evidence
- [ ] `pytest tests/unit/core/ -k "identity or measurement_spec" -q` — **to record**
- [ ] Stale-comment grep proof — **to record**

#### 8. Commit boundary
- [ ] Diff = identity/spec + tuner one-argument threading + tests +
      comment corrections; nothing else.
- [ ] Show diff summary + evidence, then commit.

---

### Commit G4 — Fallback observability and the A.9 disposition

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
- [ ] Diff = executor observability + docstrings + tests + docs.
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
   inference on ONE generated model **whose probe-derived batch ≠ 25
   (the old fallback)** — a degenerate probed==25 case would pass
   without exercising G2 (0.R.7) — showing (a) the record's forecast
   batch == runtime batch where OLD behavior would have forecast the
   fallback batch, and (b) the frozen scorer accepts the output; the
   scorer/metric implementation untouched. No throughput campaign
   (minimum sufficient evidence). All timings hardware-local (PR F
   calibration boundary).
6. Full checker set per §E.3d.12 at the final heads; CI green on the
   exact final HEAD.

## Operator decisions (rev 2 — reflecting the operator's provisional stances and the §0.R audit)

### Q-G-1 — Scope restatement — **APPROVED IN PRINCIPLE (operator, rev-1 review)**
The ledger's "remove the name-keyed fallback / name table removed from
the path" is superseded by: *the table is never consulted on the agent
production path when a probe hint exists (a property that already
holds at runtime and is pinned by G4's contract test); its remaining
consumers (baselines, legacy scripts, proposer advisory, no-hint
fallback) are documented.* Awaiting final freeze with rev 2.

### Q-G-2 — The one production-behavior change (G2) — **CONDITIONAL (operator); conditions now discharged by audit, awaiting confirmation**
The three conditions and their §0.R answers:
1. *Forecast units/formula proven* → 0.R.3: hint = measured
   ms/PSD-segment; batch cancels exactly in the measured and static
   paths; only the ×2.7 fallback path is batch-sensitive
   (conservative over-estimate). G2 must thread BOTH sides with the
   same value — one-sided threading would corrupt the measured path.
2. *`active_params` lifetime proven* → 0.R.4: fresh dict per attempt
   (:4452); stale hint impossible by construction; negative test added
   anyway.
3. *Second forecast consumer resolved* → 0.R.2: the proposer preflight
   is advisory-only, static-path (batch-invariant), and has no hint by
   construction — no threading; `estimate_peak_bytes` (inference) is
   production-dead. No live table-based forecast consumer remains
   after G2.

### Q-G-3 — Identity alignment (G3) — **RESUBMITTED, NARROWED (was: not yet approved)**
Ordering proven (0.R.5): the spec is built AFTER the hint exists and
already receives `active_params` — outcome A structurally, no
reordering. But the live path is training-phase-only, where the batch
is comparison-inert: G3 therefore claims ONLY payload truth + latent
trap closure + comment truth, and the PR-level invariant no longer
equates a measurement path that does not exist. **Approve the
narrowed G3, or defer it out of PR G** (it is severable; deferring
leaves the stale comments and the latent trap in place, recorded).

### Q-G-4 — A.9 disposition — **RESUBMITTED, NARROWED (was: not yet approved)**
Reachability proven (0.R.6): the agent-path fallback is unreachable by
construction; only baselines/legacy scripts reach the table. Therefore
NO new production observability (nothing to observe on a path that
cannot occur). G4 = the reachability-preserving CONTRACT TEST + comment
/docstring truth, zero runtime diff. A.9's "remove the fallback" is
formally retired in favor of "pin the contract that makes it
unreachable". **Approve/amend.**

### Q-G-5 — Validation criterion — **APPROVED IN PRINCIPLE (operator, rev-1 review)**
No raw byte-identity across a legitimate batch change. Frozen criteria:
no-hint parity (deep-equal breakdowns; zero behavior change off the
agent path) + same-authority coherence (forecast == runtime) + frozen
scorer/metric untouched. The Gate case must satisfy probed ≠ 25
(0.R.7). Awaiting final freeze with rev 2.

## V21 review fields

```text
Metric-frozen proof:      no scoring surface touched; guard tests
                          unmodified; frozen TIDMAD formula untouched
Name-keyed dependency
added:                    none — PR G REDUCES name-keyed reliance; the
                          table's remaining consumers are enumerated
                          and observable
Transport contract:       the probed batch's three hops (time gate,
                          identity, runtime) each carry a
                          delete-the-hop reachability test
Subprocess evidence:      runtime batch already crosses the subprocess
                          boundary today (:1543); G-commits add no new
                          boundary
Acceptance evidence:      parity matrix + coherence invariant + one
                          bounded operator-approved real inference
```

---

**Nothing in this document is implemented.** On approval of Q-G-1…Q-G-5
(or their amendments), the sequence is G1 → G2 (evidence checkpoint) →
G3 → G4 → PR-level validation. Every commit stops to show its diff
summary, staged files, test evidence, and deviations before committing.
