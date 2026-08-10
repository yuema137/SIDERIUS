# PR G — Capability-derived inference batch

**Status: DESIGN DRAFT rev 1 (2026-08-10) — awaiting operator review.
No implementation.** Fresh audit complete (§0); the audit MATERIALLY
restates the objective: the capability-derived mechanism the ledger asks
for **already exists and is live on the agent runtime path** — the
remaining work is forecast/identity coherence and closing a
half-finished migration, not building a derivation.

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
- [ ] Add optional `inference_batch: int | None = None` to the
      estimator entry points; when provided, use it in place of
      `inference_batch_for(model_type)` and record the source in the
      breakdown (e.g. `inference_batch_source: "explicit" | "table"`),
      observability only.
- [ ] Same optional input for the time-skill wrapper's `inf_batch`
      (:746), threading through the `inference_ms` scaling (:749).
- [ ] Unit tests per §4 below.

#### 4. Validation plan
- Unit: with the argument absent, the returned estimate/breakdown is
  **deep-equal** to the pre-G1 output for a registered and an
  unregistered model (parity pin); with the argument present, the
  breakdown's `inference_batch` equals the explicit value and the
  wall-time scales accordingly.
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
Close the live coherence gap (§0.C): the time-gate forecast uses the
same batch runtime will use. This is the PR's one intended
production-behavior change on the agent path, isolated here with its
own parity evidence. **Lands only after Q-G-2 approval.**

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
      call; wrapper prefers it via the G1 seam.
- [ ] Extend the C3b pin (§0.D): a new test asserting that ON THE HINT
      PATH the forecast batch equals the runtime batch (the restored
      invariant), alongside the existing no-hint pin.
- [ ] **Per-builtin parity matrix (§E.3d.7 discipline, recorded in this
      doc):** for the six shipped model types, compare the probe-derived
      batch against the table entry on the reference hardware; every
      difference explained (e.g. `transformer: 1` O(T²) vs probe
      outcome), never averaged away. Evidence recorded here before the
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
Close the latent identity trap (§0.B #4): the planned measurement
identity must carry the batch that will actually run, and the
"canonical source" comments must stop claiming table==runtime.

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
- [ ] Tuner pre-phase site passes the probed batch when the preflight
      has one (audit exact ordering at :4541-:4780 first — if the
      measurement request is built before the preflight runs, record
      that and keep the fallback with a comment, rather than reordering
      phases "while refactoring").
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
- A test proves the planned inference identity equals the batch
  production would run (hint present), and the table value only when no
  hint exists.
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
Close the never-finished A.7→A.9 migration honestly: the silent
executor fallback stays (baselines need it — Q-G-4 recommendation), but
an **agent-path** fallback firing becomes loudly observable, so the
next "generated model silently ran at 25" cannot recur unnoticed.

#### 2. Scope
- Files: `core/sandbox_executor.py` (:1543 region — record/print when
  the fallback fires, observability only), `core/inference_defaults.py`
  (docstring: the table's remaining legitimate consumers, per §0.B),
  relevant `.md` docs (doc-sync rule); tests.
- Must remain unchanged: the fallback VALUE and behavior; baselines;
  the `inference_batch_uncalibrated` flag's meaning; no new predicate.
- Dependencies: G2 (so "agent path" has its final meaning).

#### 3. Implementation plan
- [ ] Inspect how `execute_inference` results surface into records
      before choosing the observability channel (existing result dict
      vs a print — prefer the existing record path; no new schema
      category without a Pydantic model, per project rules).
- [ ] Emit the fallback fact (model_type, fallback batch) through that
      channel; observability only.
- [ ] Update `inference_defaults.py` docstring + executor comments to
      the post-G4 truth (who legitimately consults the table).
- [ ] Tests per §4.

#### 4. Validation plan
- Unit: fallback firing is recorded; hint path records nothing new.
- Negative/guard: a test proving nothing READS the new observability
  fact to make a decision (C3b discipline extended to it).
- Backward-compat: baseline scripts' behavior unchanged (no hint →
  same batch, plus the observability fact only where the record channel
  exists).

#### 5. Acceptance criteria
- A test fails if the fallback fires without being recorded on the
  record-bearing path; a guard test fails if the fact becomes a
  predicate.
- Docstring census in `inference_defaults.py` matches §0.B verbatim.

#### 6. Failure and edge cases
| Case | Behavior |
|---|---|
| Fallback on a no-record path (legacy script) | Print-level visibility only; no behavior change |
| Fallback fires because the wrapper omitted the hint on a feasible check | Recorded — this is exactly the regression the observability exists to catch |

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
2. **Coherence invariant proven:** on the agent path, forecast batch ==
   measurement-identity batch == runtime batch, with a reachability
   test per hop (delete-the-hop discipline).
3. **Parity proven:** every no-hint path byte-identical to today
   (deep-equal breakdowns; baselines untouched); per-builtin parity
   matrix recorded with every probe-vs-table difference explained.
4. **The table remains** for its documented consumers; its docstring
   census matches the audit (§0.B).
5. **Bounded real validation (PR-level Gate, operator-approved
   separately, cold-start per the standing rule):** ONE bounded real
   inference on ONE generated model on the reference GPU showing
   (a) the record's forecast batch == runtime batch, and (b) the frozen
   scorer accepts the output identically to a control at the same batch.
   No throughput campaign (minimum sufficient evidence).
6. Full checker set per §E.3d.12 at the final heads; CI green on the
   exact final HEAD.

## Operator decisions needed before implementation

### Q-G-1 — Scope restatement (supersedes the old ledger merge criteria)
The ledger's "remove the name-keyed fallback / name table removed from
the path" is replaced by: *the table is never consulted on the agent
production path when a probe hint exists; its remaining consumers
(baselines, legacy scripts, no-hint fallback) are documented and
observable.* **Approve/amend.**

### Q-G-2 — The one production-behavior change (G2)
Feeding the probed batch to the time gate changes gate INPUTS on the
agent path (forecast correctness). Lands only with the parity matrix +
extended C3b pin as evidence. **Approve direction now; final approval
at the G2 evidence checkpoint.**

### Q-G-3 — Identity alignment (G3)
Planned inference-measurement identity carries the batch that will
actually run (explicit hint preferred). **Approve/amend.**

### Q-G-4 — A.9 disposition
Recommendation: RETAIN the executor fallback + loud observability (G4),
i.e. A.9's "remove the fallback" is formally abandoned in favor of
"observe the fallback". Removing it would break baselines/legacy
scripts for zero information gain. **Approve/amend.**

### Q-G-5 — Validation criterion replacing "byte-identical outputs"
Byte-identity is only sound at an unchanged batch. Proposed criteria:
no-hint paths byte-identical; hint paths validated by the coherence
invariant + frozen-scorer acceptance (metric untouched), not raw output
bytes across different batches. **Approve/amend.**

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
