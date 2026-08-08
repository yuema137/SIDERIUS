# PR B — Resource-budget semantics and estimator correctness

**Status: APPROVED 2026-08-08 (operator) with four corrections applied.
B1 + B2 IMPLEMENTED; B0 evidence packet next. STOP for operator review at
B0 before writing B3.**

> **B1's audit changed this document.** Three claims in §0.4 and §0.2 did
> not survive contact with the code, and the corrections are attached in
> place rather than edited away: the headline `segmentation_size` defect
> had its **direction backwards**, FU-C-1 turned out to be **latent**
> because the analytic VRAM estimator has had no production caller since
> April, and the sweep found the one genuinely optimistic defect —
> **`epochs`** — that §0.4 had missed entirely. §0.6 records all of it.

> **Q-B-1 is DEFERRED BY DESIGN, not unresolved.** It blocks **B3 only** —
> it does **not** block B1 or B2. Part III's sequence is *audit semantics →
> freeze semantics (operator decision, written) → implement enforcement*,
> and the audit is strongest when it can cite corrected forecasts (B1) and
> measured forecast error (B2) rather than V20's three OOMs alone.
>
> ```text
> B1 → B2 → B0 evidence review → operator freezes S1/S2/S3 → write B3
> ```
>
> The operator's current prior is **S3**, recorded and **explicitly not
> frozen**. B1/B2 evidence decides whether corrected forecasting suffices
> or whether stronger runtime enforcement is justified. This document
> proposes **no enforcement mechanism**.

| | |
|---|---|
| Plan section | `docs/design/v21_priorities.md` Part III, PR B (B-1 + B-2) + §E.3b |
| Gate | V21 launch blocker |
| Depends on | PR A (`b9f88ae5`), PR C (`cac86c94`) — both merged |
| Audit date | 2026-08-08, against `master` `ece24a02` |

**The question PR B answers.**

```text
PR A   the agent can invent classification AND regression correctly
PR C   what it invents is a production first-class citizen
PR B   what the system PREDICTS about a candidate's resource use is
       true enough to decide with, and what it DECIDES is enforced
```

---

## A0. Verification toolchain

Inherited and verified working:

```bash
PYRIGHT_PYTHON_GLOBAL_NODE=off uv run pyright     # pyright 1.1.409
.venv/bin/python -m pytest tests/unit/ -q -m "not real_run"
.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .
```

**Baseline at `ece24a02`:** unit suite `7951 passed, 2 skipped, 1 xfailed`;
pyright `0 errors, 4 warnings`; ruff clean.

Production launchers are blocked by `require_launch_approval.sh`
(`SIDERIUS_ALLOW_LAUNCH=1` to declare); git/gh mutations by
`require_commit_approval.sh` (`SIDERIUS_GIT_APPROVED=1`).

---

## 0. Pre-implementation audit (performed 2026-08-08)

Five findings. **The first reframes PR B entirely, and the fourth makes
B-2 larger than FU-C-1 alone.**

### 0.1 Enforcement was already ON in V20 — so "add enforcement" is the wrong verb

Part III frames B-1 as *"is the 12 GiB an enforced cap or an admission
estimate?"*, with the implication that enforcement may be missing. It is
not missing.

`sdsc_submission_scripts/launch_v20_campaign.sh:189` launches with:

```bash
--gpu_admission_enforcement enforce_resource_limits
```

and its own banner (`:227`) prints
`admission=enforce_resource_limits, order=sequential`. The schema field
(`hyperparam_tuning.py:1633`) documents that value as *"the V20 PRODUCTION
posture: a resource verdict (`insufficient_headroom`) stops the phase"*.

So P6.4's evidence — ~20.13 GiB realized against a declared 12 GiB budget,
three OOMs in 34 minutes — happened **with enforcement enabled and chains
running sequentially**. That rules out the two easiest explanations
(enforcement off; peer contention) and points at a third.

### 0.2 What the 12 GiB actually caps is a PREDICTION

`evaluate_vram_skill/wrapper.py:490-492` and `:530-532`:

```python
# vram_budget_gb — operator-set soft cap. When set, the effective
#                  cap is min(ctx.usable_cap_bytes, int(vram_budget_gb * GB))
cap_bytes = physical_cap_bytes
if vram_budget_gb is not None:
    cap_bytes = min(cap_bytes, int(vram_budget_gb * _GB))
```

The budget lowers the cap that an **estimated** peak is compared against.
The schema calls it an *"Operator-defined ceiling — set conservatively so
the gate rejects models that exceed it"* — language that describes a limit
on *actual* usage, while the code limits a *forecast*.

```text
DECLARED   "no candidate uses more than 12 GiB"
IMPLEMENTED "no candidate is admitted whose PREDICTED peak exceeds 12 GiB"
```

Those differ by exactly the estimator's error, in whichever direction the
estimator errs.

**Leading hypothesis for B-1, to be confirmed by B0's audit and not
asserted here:** enforcement worked, and enforced a number that was wrong.
A candidate whose true peak was ~20 GiB was predicted under 12 GiB,
admitted correctly under the implemented semantics, and then OOMed.

### 0.3 Nothing compares REALIZED phase memory back to what was admitted

Searched for a realized-vs-admitted comparison. Exactly one cap comparison
exists, and it is in the wrong place for this purpose —
`gpu_measurement_classifier.py:212`:

```python
if vram_cap_mib is not None and target.driver_tree_peak_mib > vram_cap_mib:
    return ("MEASURED_PEAK_ABOVE_VRAM_CAP", ...)
```

That is the **pre-phase measurement worker** judging its own measurement.
The production training and inference phases record `allocator_peak_mib` /
`driver_tree_peak_mib`, but **no code path compares those to the budget the
phase was admitted under.** So an under-prediction is invisible unless it
happens to OOM — and an OOM reports as an OOM, not as a broken forecast.

This is Part III's stated requirement, still unmet: *"a candidate's
realized phase memory cannot persistently exceed its admitted budget
without the system recording it."*

### 0.4 The config-default vs estimator-fallback mismatch class is bigger than FU-C-1

FU-C-1 was handed to PR B as one wrong constant. The sweep the operator
required found it is a **class**. Measured at `ece24a02`:

| field | config-class default | VRAM estimator fallback | wall-time estimator fallback |
|---|---|---|---|
| `segmentation_size` | **40000** (5 models) / **20000** (transformer) | `40000` | **`1000`** |
| `nhead` | **4** (transformer) | `2` | `2` |
| `num_layers` | `2` | `2` | `2` |

Three distinct defects, and they do not all point the same way:

1. **`nhead` 4 → 2 (FU-C-1).** Attention memory under-counted ~2x.
   **Optimistic** — the dangerous direction.
2. **`segmentation_size` 40000 → 1000 in the wall-time path**
   (`training/estimator.py:414`, `inference/estimator.py:236`). A **40x**
   under-estimate of steps, hence of time, whenever the dict omits the
   key. **Optimistic**, and an order of magnitude larger than FU-C-1.
   Feeds `skipped_time_risk` and the formal-time budget.
3. **`segmentation_size` for `transformer`: config 20000, estimator
   fallback 40000.** A 2x **over**-estimate — the safe direction, but
   still a mismatch, and it means the same field is wrong in *both*
   directions depending on the model.

Two fallbacks for the same field, 40x apart, live in the same file
(`estimate_peak_bytes` uses 40000, `estimate_wall_time_seconds` uses 1000).

> Whether any of these is *reached* in production depends on whether the
> caller's dict carries the key. **B1's audit must establish reachability
> per site before changing any value** — that is the same discipline C3
> applied when it pinned `nhead` rather than guessing.

> ### ⚠ CORRECTION 2026-08-08 — §0.4 item 2 states the direction BACKWARDS
>
> Written before the reachability audit, on reasoning rather than
> measurement. **B1's audit (§0.6) measured it and item 2 is wrong.**
>
> Smaller `seg_size` produces **more** steps, not fewer
> (`ml_per_psd = 10_000_000 // seg`), and the static ms/step is
> **proportional** to `seg_size`, so the two cancel exactly. Measured
> across a six-decade parameter sweep, the `1000` fallback is **never
> optimistic**: ratio `1.000` in the un-floored regime and up to **40x
> CONSERVATIVE** once `_MIN_MS_PER_STEP` binds (§0.6.3).
>
> Item 2's "40x optimistic, an order of magnitude larger than FU-C-1" is
> retracted. The real active optimistic defect in this class is
> **`epochs`**, which §0.4 missed entirely (§0.6.4).
>
> Items 1 and 3 are arithmetically correct but describe an **orphaned**
> function — see §0.6.2. The table above stays as written, with this
> correction attached, per the mandate's rule against silently rewriting
> the record.

### 0.5 `max_active` bounds chains, not GPU phases

Inherited from PR A's §E.3b and unchanged. PR A and PR C both ran their
Gates **sequentially** for this reason, so **neither tested concurrency**.
PR B is where that is answered — and note 0.1: V20 attempt 3 was itself
sequential, so concurrency is not required to reproduce the P6.4 evidence.

---

## 0.6 B1 reachability audit — performed 2026-08-08 at `8cb604d8`

Required by B1's §3 first checkbox and by the mandate's §4.1: classify
every site **before** changing a value. The audit changed the shape of
B1 substantially, so it is recorded in full rather than summarised.

Method: static producer→consumer tracing, git archaeology on the call
sites, config-class introspection, and a measured parameter sweep
(`estimate_wall_time_seconds` / `estimate_peak_bytes` driven directly).
No GPU, no training.

### 0.6.1 Nothing requires these keys — every fallback is genuinely reachable

`ExperimentPlan` (`agent/schemas/hyperparam_tuning.py:795-809`) declares

```python
model_cfg: dict[str, Any] = Field(default_factory=dict, alias="model_config")
train_cfg: dict[str, Any] = Field(default_factory=dict, alias="train_config")
```

with **no required keys and no validator** forcing `segmentation_size` or
`epochs`. `ProposalOutput._validate_baseline_segmentation_size`
(`proposal.py:1084`) explicitly no-ops when the key is absent — *"some
architectures don't have one"*. Both production entry points then pass the
dict through untouched:

```text
nodes/ml_model_proposal_agent:186   model_config=baseline.get("model_config") or {}
tuner:1328                          model_config=active_params.get("model_config") or {}
```

So an LLM plan omitting the key is legal at every hop, and reaches the
fallback. **Reachability is established for the wall-time sites.**

### 0.6.2 The VRAM estimator has had NO production caller since 2026-04-23

The finding that most changes B1. `estimate_peak_bytes` — in **both**
estimators — is called only from tests.

```text
grep estimate_peak_bytes  --> definitions, docstrings, tests. No production caller.
grep attention_shape      --> defined + called ONLY inside the two estimate_peak_bytes
```

Cause, from git: commit `8b6c4ba8` *"feat(evaluate_vram_skill): A.8 —
deterministic wrapper rewrite"* (2026-04-23) replaced the analytic
estimate with a **deterministic probe**
(`probe_activation_footprint` → `_compose_training_peak`). Its diff
removes exactly these three lines:

```diff
-        training_phase  = _training_est.estimate_peak_bytes(
-        inference_phase = _inference_est.estimate_peak_bytes(
-        scoring_phase   = _scoring_est.estimate_peak_bytes()
```

Ruled out as well: string/`getattr` dispatch (none), and any probe-failure
path falling back to the analytic estimate (`evaluate_vram_skill` contains
no reference to it at all).

**Three consequences.**

1. **FU-C-1 is LATENT, not active.** `attention_shape`'s only callers are
   the two orphaned functions, so the `nhead` 4→2 under-count reaches no
   admission decision. It is still wrong and B1 still corrects it, but
   this document must stop implying it cost V20 anything.
2. **§0.2's leading hypothesis is FALSIFIED for VRAM.** The 12 GiB
   admission number comes from a probe, not from these fallbacks.
   **B1 cannot explain P6.4's OOMs**, and B0 must not be written as
   though it might. What B1 fixes is the *time* forecast and a set of
   latent VRAM-estimator inputs.
3. B1's parity table splits in two: **ACTIVE** sites, where a change
   moves a real production forecast, and **LATENT** sites, where it does
   not. Reporting one number for both would overclaim.

### 0.6.3 Measured direction — the `1000` fallback is never optimistic

`punet`, sample set of 40 PSD segments, `batch_size=1`, `epochs=1`,
static path, fallback `1000` vs canonical `40000`:

| num_params | ms/step @1000 | ms/step @canon | sec @1000 | sec @canon | fallback ÷ canonical | direction |
|---|---|---|---|---|---|---|
| 1,000 | 2.000 | 2.000 | 1040.0 | 26.0 | **40.000** | CONSERVATIVE |
| 10,000 | 2.000 | 2.000 | 1040.0 | 26.0 | **40.000** | CONSERVATIVE |
| 100,000 | 2.000 | 12.000 | 1040.0 | 156.0 | **6.667** | CONSERVATIVE |
| 1,000,000 | 3.000 | 120.000 | 1560.0 | 1560.0 | 1.000 | neutral |
| 10,000,000 | 30.0 | 1200.0 | 15600.0 | 15600.0 | 1.000 | neutral |
| 100,000,000 | 300.0 | 12000.0 | 156000.0 | 156000.0 | 1.000 | neutral |

Lowest ratio anywhere in the sweep: **1.0000**. Inference static path:
`1.0000` throughout.

Why: `total_steps ∝ 1/seg` and `_static_ms_per_step ∝ seg`, so the product
is invariant — until `_MIN_MS_PER_STEP = 2.0` floors the small-model end
and breaks the cancellation in the **conservative** direction.

**Correcting this site therefore makes the estimate SMALLER** (up to 40x)
for small models. That is a move in the optimistic direction and is
permitted only on §1.1's terms, which are met and recorded in §0.6.6.

### 0.6.4 The sweep found an ACTIVE OPTIMISTIC defect §0.4 missed: `epochs`

Q-B-3 bounded the sweep to config/default inputs consumed by the two
estimators. Extending it past `segmentation_size` as instructed:

| field | estimator fallback | config-class default | verdict |
|---|---|---|---|
| `batch_size` | `1` | `TrainConfig` `1` | **NOT A DEFECT** — matches |
| `optimizer_type` | `"adamw"` | `TrainConfig` `"adamw"` | **NOT A DEFECT** — matches |
| `epochs` | **`1`** | `TrainConfig` **`10`** | **ACTIVE, OPTIMISTIC, 10x** |
| `loss_type` | `"ce"` | `LossConfig` `"focal"` | latent (orphaned path) |

`epochs` is the defect §0.4 was looking for and mis-attributed to
`segmentation_size`: time scales **linearly** in epochs with no
cancelling term, so an omitted `epochs` makes the forecast **10x
optimistic** — the dangerous direction, in a reachable path, feeding
`skipped_time_risk` and the formal time budget.

### 0.6.5 Two findings OUTSIDE B1's scope — reported, not fixed here

**(a) An omitted `epochs` defeats the `--max_epochs` hard cap.**
`tuner:4052`

```python
planned_epochs = plan.train_cfg.get("epochs", 1)
if planned_epochs > agent_input.max_epochs:      # 1 > 1 is False -> no clamp
```

while the trainer builds `TrainConfig(**t_data)`
(`train_engine_sandbox.py:1211`) and gets **10**. So a plan omitting
`epochs` runs **10 epochs under `--max_epochs 1`**.

```text
plan omits epochs
  -> clamp sees 1, does not clamp        (--max_epochs defeated)
  -> time estimator prices 1 epoch       (10x optimistic)
  -> trainer actually runs 10 epochs
```

This violates the binding rule that **the harness owns the bounds, not
the planner**. It is a training-behaviour defect, not an estimator input
fact, so B1 does not touch it — fixing it would change what production
trains. **Escalated to the operator** (§0.6.7).

**(b) The observation-store key is built from the fallback.**
`evaluate_time_skill/wrapper.py:628` resolves `seg_size` with the same
`1000` default and passes it to `calibration_key(..., seg_size=seg_size)`
(`:501`). A run whose model really runs at 40000 would read and write a
store bucket labelled 1000, mixing incomparable measurements. Correcting
the resolution at `:628` fixes this as a side effect; the keying question
itself belongs with B2's provenance work.

Also recorded, not actioned: `tuner:1310` uses a **third** default for the
same field, `.get("segmentation_size", 0)`, feeding
`ProbeRequest.workload["segment_length"]`. A bucket key of `0` collides
every unlabelled run into one bucket. Routed to B2.

### 0.6.6 Site inventory and verdicts

`A` = active (a production forecast moves), `L` = latent (correct but
unreachable today).

| # | Site | Field | Fallback | Canonical | Reach | Direction if corrected |
|---|---|---|---|---|---|---|
| S1 | `training/estimator.py:130` | `nhead` | `2` | `4` (transformer) | **L** | larger (conservative) |
| S2 | `training/estimator.py:131` | `num_layers` | `2` | `2` | L | **none — not a defect** |
| S3 | `training/estimator.py:233` | `segmentation_size` | `40000` | class default | **L** | smaller for transformer |
| S4 | `training/estimator.py:414` | `segmentation_size` | `1000` | class default | **A** | smaller (up to 40x) |
| S5 | `inference/estimator.py:120` | `segmentation_size` | `40000` | class default | **L** | smaller for transformer |
| S6 | `inference/estimator.py:236` | `segmentation_size` | `1000` | class default | **A** | neutral |
| S7 | `evaluate_time_skill/wrapper.py:628` | `segmentation_size` | `1000` | class default | **A** | fixes the store key |
| S8 | `training/estimator.py:416` | `epochs` | `1` | `10` | **A** | **larger — closes a 10x optimism** |

**The canonical source, proven rather than assumed.** For every one of
these fields it is the **config class default**, and the proof is
internal to the estimator: `estimate_wall_time_seconds` already calls
`_count_params` → `config_cls(**model_config)`, so Pydantic resolves the
*same absent key* to the class default in the *same call* that `.get()`
resolves it to `1000`. The function contradicts itself. The model whose
parameters are counted at `seg=40000` has its steps priced at `seg=1000`.

### 0.6.7 Corrections this audit forces on the approved design

- [x] **§0.4 item 2's direction is retracted** — correction attached in
      place, evidence in §0.6.3.
- [x] **B1's acceptance criterion "the VRAM and wall-time paths agree on
      `segmentation_size` for identical input — the 40x split cannot
      return" is UNSAFE AS WRITTEN and is amended.** The two phases have
      *opposite* conservative directions: for VRAM a larger `seg` is the
      safe error, for wall time a smaller `seg` is. Forcing the two
      literals to one value necessarily makes one phase more optimistic,
      which §1.1 forbids. **Amended to:** where a canonical source
      exists the two paths must resolve to *the same canonical value*,
      which removes the split for every model that declares the field;
      only where no declaration exists may a phase-appropriate value
      remain, documented as a **safety margin**.
- [x] **§0.2's leading hypothesis is falsified for VRAM** (§0.6.2).
      B0 must not present B1 as a candidate explanation for P6.4.
- [ ] **OPERATOR DECISION REQUESTED — the `--max_epochs` bypass
      (§0.6.5a).** Out of B1's scope, changes training behaviour, and
      defeats a bound the operator rules call binding. Not fixed here.

## 0.7 B2 capture-point audit — performed 2026-08-08

Required by B2's §3 first checkbox. Read-only; no code changed.

### 0.7.1 §0.3's premise is half wrong: there is no realized peak to compare

§0.3 stated *"the production training and inference phases record
`allocator_peak_mib` / `driver_tree_peak_mib`, but no code path compares
those to the budget."* The first clause is false.

Both field names exist **only** in `core/runtime_control/gpu_measurement_*`
— the pre-phase measurement worker — plus `scripts/`. A sweep of every
CUDA memory API across the repository finds **nothing** in
`execute_tools/`, `core/sandbox_executor.py`, `nodes/`, or either phase
skill:

```text
grep max_memory_allocated|max_memory_reserved|memory_allocated
     |memory_reserved|mem_get_info
  execute_tools/ core/sandbox_executor.py nodes/
  agent/skills/training_skill/ agent/skills/inference_skill/
  -> no matches
```

The only production callers anywhere are
`core/runtime_control/probe_production.py:296` (the bounded probe) and
`gpu_milestone_trace.py:577` (tracing), neither of which is the
production training or inference phase.

**So B2 is larger than "add a comparison": the realized quantity is not
measured at all.** B2 must add the measurement *and* the comparison. It
remains observation-only — nothing decides on it — so the commit's
character is unchanged, but its scope is not what §0.3 assumed.

### 0.7.2 The omission was deliberate, and its stated reason has expired

`docs/phase66_telemetry/capture_stage2_vram_telemetry.py:20-26` records
the decision explicitly:

> *"this is a one-off measurement artefact. It does NOT modify any
> production code path. The alternative — wiring `max_memory_allocated`
> into sandbox_executor — would require touching the subprocess entry
> points for a single one-time reading; not worth the blast radius."*

That reasoning was correct for a one-time reading. It does not survive
P6.4: the realized peak is no longer a curiosity, it is the evidence
Q-B-1 turns on, and §0.3's finding is that an under-prediction is
invisible unless it happens to OOM. The cost/benefit has inverted.

The note is also a useful warning about *where* the work lands — the
subprocess entry points — which is the boundary B2 must justify touching
and the reason B2 audits before writing.

### 0.7.3 The ADMITTED half already exists and is already persisted

`evaluate_vram_skill.run_skill` returns, on both the feasible and the
infeasible path:

| returned key | B2 neutral field it supplies |
|---|---|
| `estimated_gb` | `admission_estimated_peak_mib` |
| `limit_gb` (`cap_bytes`) | `effective_admission_threshold_mib` |
| `vram_budget_gb` | operator-budget context |
| `dominant_phase`, `phase_breakdown` | phase attribution |

So B2 does **not** need to invent the admitted half or thread it
anywhere new. Two gaps remain on this side, both small:

- **The physical cap is not a returned field** — it exists as
  `hardware_context.usable_cap_bytes` and reaches the record only inside
  the `verdict` prose.
- **The binding-cap classification is a print, not a fact.**
  `wrapper.py:538-545` already computes exactly the three regimes B2
  needs (`PHYSICAL` / `PHYSICAL VETO` / `BUDGET`) and assigns them to
  `cap_note`, a **log string**. This is precisely the "value that is only
  printed" pattern the mandate rejects as evidence. B2 should promote the
  existing classification to a typed field rather than write a second
  one — a second implementation could disagree with the log.

### 0.7.4 The shape of B2, and the one escalation risk

```text
ADMITTED   exists, typed, persisted          -> reuse
REALIZED   does not exist anywhere           -> B2 must capture it
TRANSPORT  the two do not meet in any scope  -> the real design question
```

The realized peak has to be read inside the **training and inference
subprocesses**, which is the boundary the phase-6.6 note called "blast
radius". Whether that is a *bounded* addition at an existing typed
subprocess boundary or a *material* architecture change is the question
B2 answers first. If it turns out to require broad state threading, a
new singleton, or a new runtime-control mechanism, the mandate's §12
rule applies: **STOP AND ESCALATE** rather than build it.

### 0.7.5 Consequence for B0

Until B2 lands and runs, **there is no measured realized-vs-admitted
distribution at all**, and none can be reconstructed from V20 artifacts
that never recorded one. B0 must say so plainly rather than infer a
distribution from three OOMs. Recorded here so the B0 packet cannot
quietly overclaim.

---

## 1.1 Operator rulings, 2026-08-08 — read before B1

Four corrections to this document, two of which fix defects in it.

### Q-B-1 — DEFERRED BY DESIGN, not unresolved scope

**Do not choose S1/S2/S3 yet.** Q-B-1 blocks **B3 only**. Proceed
`B1 → B2 → B0 evidence review → operator freezes → write B3`.

The operator's prior is **S3**, explicitly **not frozen**:

```text
B1 leaves no meaningful under-prediction   -> S1 or S3 more reasonable
B1 leaves large under-prediction, enough
  to OOM                                   -> the case for S2 strengthens
```

> PR B's real value is that we no longer have to reason backwards from
> three OOMs to what "12 GiB" ought to mean. We fix the forecast first,
> measure forecast-to-realization error second, and let data choose the
> semantics third.

### Q-B-2 — YES, B1 may change built-in estimates

C3's byte-parity constraint is **lifted for this bounded, audited defect
class only**. Per changed cell, record: canonical source, previous value,
corrected value, magnitude, direction, **production reachability**.

```text
ALLOWED      declaration says X, estimator substitutes unrelated Y
             -> correct Y to the audited canonical value

NOT ALLOWED  "this estimate seems wrong"
             -> invent a coefficient, formula or safety factor
```

**B1 may change the estimator's input FACTS. It may not change the
estimator's MODEL.** Update C3's guard to assert the corrected value;
do not delete it.

### Q-B-3 — YES, the `segmentation_size` mismatches are in B1

Same defect class as FU-C-1 and larger in effect. Fixing `nhead` alone
would fix the reported instance and leave the class alive. Sweep bounded
to **config/default inputs consumed by the training and inference resource
estimators** — not a repository-wide config-default cleanup.

### CORRECTION — the "never more optimistic" rule contradicted itself

The first draft of this document required **both** that every fallback
match its canonical source **and** that no estimate ever become more
optimistic. Those conflict on a case §0.4 itself found: if the canonical
`segmentation_size` for `transformer` is 20000, correcting `40000 → 20000`
makes the estimate **smaller**.

Held absolutely, the rule would force keeping a value known to be false
while calling it a config fallback — less safe *and* less honest. Replaced
with:

> **No estimate may become more optimistic accidentally, silently, or
> without evidence.**

```text
correction makes the estimate LARGER
  -> routine audited correction

correction makes the estimate SMALLER
  -> prove the canonical source
  -> record the exact before/after magnitude
  -> explain why the old value was semantically wrong
  -> preserve the estimator formula
  -> validate the consequence with B2 / B4 evidence

canonical source UNCERTAIN
  -> do not guess. Keep the conservative value and document it honestly
     as a SAFETY MARGIN, never as "the model default"
```

### CORRECTION — B2 must be semantics-neutral

Because Q-B-1 is not frozen until B0, B2 may not encode a policy verdict as
a primitive fact. `budget_breach = true` would already have chosen a
semantics.

B2 persists **measured facts**:

```text
admission_estimated_peak_mib
effective_admission_threshold_mib
realized_peak_mib
realized_minus_estimated_mib
realized_minus_threshold_mib
realized_above_threshold: bool
measurement_completeness
owning_process
```

After B0, the frozen semantics **interprets** the same observation:

```text
S1 -> forecast error / threshold exceedance
S2 -> cap violation
S3 -> recorded budget breach / escalation event
```

---

## 1. Commit plan

| # | Commit | Blocked on | Independently reviewable |
|---|---|---|---|
| **B1** | Config-default vs estimator-fallback sweep (FU-C-1 + siblings) | nothing — **explicitly not Q-B-1** | Yes |
| **B2** | Record realized-vs-admitted, **semantics-neutral** | nothing — **explicitly not Q-B-1** | Yes |
| **B0** | **Semantics audit + options → OPERATOR FREEZES** | B1, B2 evidence | Yes (document) |
| **B3** | Enforcement consistent with the frozen semantics | **Q-B-1** — the only commit it blocks | Yes |
| **B4a** | Gate rung 1-2: synthetic accounting + controlled allocator holder | B3 | Yes |
| **B4b** | Gate rung 3-4: production admission path + minimal real confirm | B4a | Yes |

**Why B1 and B2 precede the semantics decision.** Both are true regardless
of which semantics the operator picks: a fallback that contradicts the
config class is wrong under *any* definition of "budget", and recording
realized-vs-admitted is the measurement that makes the semantics question
answerable with data instead of opinion. Doing them first also means B0's
audit can cite real breach numbers rather than only V20's three OOMs.

**Why B3 cannot be written yet.** Part III forbids pre-committing to a
mechanism, and the mechanism is an *output* of Q-B-1. B3's section below
deliberately contains a plan for **producing** the plan, not the plan.

### Binding principles inherited

1. **Gradual genericization** — in-passing, never a big-bang rewrite.
2. **Complete transport contract** — parent reachability is never evidence
   of subprocess reachability.
3. **The metric is frozen.**
4. **No estimate may become more optimistic accidentally, silently, or
   without evidence.** *(Corrected by the operator, 2026-08-08 — see §1.1;
   the absolute form contradicted B1's own goal.)*
5. **Built-in estimates change only with written justification and
   operator approval** (this is what made C3 pin FU-C-1 rather than fix
   it; B1 is where the approval is sought).
6. **Real training is never the discovery tool** — Part III's escalation
   ladder, rungs 1→4.

---

## Commit B1 — Config-default vs estimator-fallback sweep

### 1. Goal

Make every estimator fallback agree with the config class it is standing
in for, so an admission decision is not made on a number that contradicts
the model's own declaration.

This is **B-2 / FU-C-1** as assigned at PR C's merge, plus the two
siblings §0.4 found. It solves the defect class, not the one instance.

**Why this commit and not another.** It is the only PR B work that is
independent of Q-B-1: whatever "budget" turns out to mean, a forecast
built on `nhead=2` for a model that declares `nhead=4` is wrong. It also
comes first because §0.2's leading hypothesis is that enforcement enforced
a wrong number — B1 is the commit that tests that hypothesis by fixing the
numbers.

### 2. Scope

**Changes**
- `agent/skills/training_skill/estimator.py` — `attention_shape` (`:83`),
  `estimate_peak_bytes` (`:233`), `estimate_wall_time_seconds` (`:414`).
- `agent/skills/inference_skill/estimator.py` — `estimate_peak_bytes`
  (`:120`), `estimate_wall_time_seconds` (`:236`).
- `tests/unit/agent/test_estimator_predicates_not_names.py` —
  `test_builtin_attention_values_are_the_pre_c3_literals` **must be
  updated, not deleted.** It exists to stop FU-C-1 drifting before PR B
  corrects it; deleting it would remove the regression guard along with
  the defect.
- Tests.

**Must remain unchanged**
- C3's guarantee: a generated attention model stays **property-derived**,
  never name-keyed. B1 changes *values*, not *predicates*.
- The metric, the scorer, every score.
- Estimates for any model/field combination the audit finds already
  correct.

**Explicit non-goals**
- Changing what the estimator *models* (no new memory terms, no new
  time model). B1 corrects inputs, not formulas.
- Anything about enforcement (B3) or breach recording (B2).

**Dependencies:** none.

**This commit changes built-in estimates, which C3 deliberately did not.**
That is the whole point of the reassignment, and it is why every changed
cell must be recorded with its before/after value and its direction.

### 3. Implementation plan

- [x] **Reachability audit first, per site.** Done — §0.6, with the site
      inventory and A/L verdicts in §0.6.6. It found that three of the
      six sites are **latent** (the VRAM estimator has had no production
      caller since `8b6c4ba8`) and that the one **active optimistic**
      defect is `epochs`, which §0.4 had missed
- [x] Determine the **canonical source** of each field. It is the config
      class default, and the proof is internal rather than assumed:
      `estimate_wall_time_seconds` already resolves the same absent key
      through `config_cls(**model_config)` one line from where `.get()`
      resolved it differently (§0.6.6)
- [x] Distinguish an **absent** value from an **explicit override**,
      including an explicit value equal to the default, and from an
      explicit `None`. Implemented in `_usable` / `resolve_model_field`;
      tested in `TestResolutionOrder` and `TestUnusableValues`
- [x] Correct `attention_shape`'s `nhead` / `num_layers` fallbacks —
      FU-C-1 closed, `(2, 2)` → `(4, 2)` for `transformer`
- [x] Correct the `segmentation_size` fallbacks in **all four** estimator
      entry points. The 40000-vs-1000 split is resolved **by making both
      consult the declaration**, not by picking one literal — see
      §0.6.7, which records why picking one would have been unsafe
- [x] Sweep for any remaining config-default vs fallback mismatch across
      both estimators — §0.6.4. `batch_size` and `optimizer_type` match
      and are **not** defects; `epochs` does not; `loss_type` differs but
      only on the orphaned path
- [x] Capture the built-in parity table before and after (§B1.R), split
      into ACTIVE and LATENT so a latent correction is not reported as a
      production change

### 4. Validation plan

**Unit**
- [ ] Per field and per model: config-class default → estimator uses that
      value. `transformer` `nhead=4` → estimator uses **4**
- [ ] Explicit override `nhead=N` → estimator uses **N**, including
      `N` equal to the default
- [ ] `segmentation_size` resolves identically in the VRAM and wall-time
      paths for the same input — the 40x split cannot return
- [ ] A generated attention model remains property-derived (C3's
      guarantee), asserted by re-running C3's own tests unchanged

**Negative / invalid input**
- [ ] A model whose config class declares none of these fields
- [ ] An explicitly invalid value (`nhead=0`, negative
      `segmentation_size`) — must not silently become a fallback
- [ ] An unregistered model, where `get_config_class` returns `None`:
      must not raise inside a planning-time estimator (C3 established
      that a *refused* estimate becomes a *rejected* candidate)

**Backward compatibility / default parity**
- [ ] The extended built-in parity table, before vs after, with **every**
      difference enumerated and its direction stated
- [ ] Every cell that moves in the optimistic (smaller) direction carries
      its §1.1 justification — canonical source, magnitude, why the old
      value was wrong. A cell that moves without one is a stop-and-escalate
- [ ] The estimator formulas are byte-identical; only input resolution
      changed
- [ ] Full unit suite; C3's and PR C's batteries unchanged

**Real-training Gate:** none. B1 is arithmetic; a GPU cannot tell you
whether a fallback matches a declaration.

### 5. Acceptance criteria

- Every fallback in §0.4 either matches its canonical source or is
  recorded as deliberately different **with the reason**.
- `transformer` `nhead` default → estimator uses `4`; explicit `N` → `N`.
- The VRAM and wall-time paths agree on `segmentation_size` for identical
  input.
- The before/after parity table is published in this document, and every
  changed cell records **canonical source, previous value, corrected
  value, magnitude, direction, and production reachability** (Q-B-2's
  required fields).
- **No estimate is more optimistic accidentally, silently, or without
  evidence.** A correction that makes an estimate *smaller* is permitted
  only with the canonical source proven, the magnitude recorded, and a
  written explanation of why the old value was semantically wrong — see
  §1.1. A correction that makes it larger is routine.
- **The estimator's formulas are unchanged.** B1 corrects input facts; it
  does not add a coefficient, a term or a safety factor.
- C3's property-derived guarantee holds — C3's tests pass **unmodified**.
- `test_builtin_attention_values_are_the_pre_c3_literals` is **updated to
  assert the corrected value**, still present, still failing if the value
  drifts.
- **Mutation:** reverting each corrected fallback to its old literal turns
  a test red — one mutation per corrected site, not one for the group.

### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| A fallback is **never reached** in production | Correct it anyway (it is still wrong), but record it as latent and do **not** claim a production defect was fixed |
| No canonical source exists for a field | **STOP AND ASK.** Inventing one is the surrogate-predicate error C3's plan forbade |
| A correction makes an estimate **smaller** | Permitted, but only on the §1.1 terms: canonical source proven, magnitude recorded, old value shown to be semantically wrong, formula untouched. Never as a judgement call |
| An estimate would shrink but the canonical source is **uncertain** | **Do not guess.** Keep the conservative value and document it as a **safety margin**, explicitly not as "the model default" |
| A change is motivated by "this estimate seems wrong" rather than a proven mismatch | **Out of scope.** That is a formula change, which Q-B-2 does not authorise |
| Explicit value equals the class default | Must be indistinguishable in outcome, but the resolution path must not depend on the coincidence |
| `get_config_class` returns `None` (unregistered) | Conservative estimate, never a raise, never optimistic — C3's `_output_contract` precedent |
| A correction changes a **generated** model's estimate | Expected and fine, provided it is property-derived and not more optimistic |
| Legacy record replay | Estimators are planning-time; if any replay path calls one, record it and do not change replay semantics |

### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/agent/ -q -k "estimator or vram or time"
.venv/bin/python -m pytest tests/unit/agent/test_estimator_predicates_not_names.py -q
.venv/bin/python -m pytest tests/unit -q -m "not real_run"
.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .
PYRIGHT_PYTHON_GLOBAL_NODE=off uv run pyright
```

- [x] Reachability verdict per fallback site — §0.6.6
- [x] Before/after parity table — §B1.R below
- [x] Mutation results, one per corrected site — §B1.R
- [x] Test counts + wall time — §B1.R

### B1.R — Implementation record, 2026-08-08

**Changed files**

```text
agent/skills/training_skill/estimator.py     + resolve_model_field / resolve_train_field
                                               / _declared_default / _usable; 5 sites
agent/skills/inference_skill/estimator.py    2 sites
agent/skills/evaluate_time_skill/wrapper.py  3 sites
tests/unit/agent/test_estimator_predicates_not_names.py   C3 guard UPDATED, +2 cases
tests/unit/agent/test_estimator_input_resolution.py       new, 19 cases
```

**The formulas are untouched.** No coefficient, term or safety factor was
added, removed or changed. `SAFETY_MULTIPLIER`, `_STATIC_MS_PER_FLOP`,
`_MIN_MS_PER_STEP`, `_INFERENCE_VS_TRAINING_RATIO` and every arithmetic
expression are byte-identical. B1 changed only how three input facts are
*resolved* — Q-B-2's boundary.

#### ACTIVE sites — what a production forecast actually does now

Driven through `evaluate_time_skill.run_skill`, the entry point the tuner
calls. `rnn`, 400 PSD segments, 1M params, static path. "Before" is
reproduced by passing the old literal explicitly, which is arithmetically
identical to the pre-B1 absent-key behaviour.

| absent key | quantity | before | after | Δ | direction |
|---|---|---|---|---|---|
| `segmentation_size` | `total_train_steps` | 4,000,000 | **100,000** | ÷40 | corrected |
| `segmentation_size` | `estimated_minutes` | 369.84 | **369.84** | ×1.00 | **unchanged** |
| `epochs` | `total_train_steps` | 250,000 | **2,500,000** | ×10 | corrected |
| `epochs` | `estimated_minutes` | 369.84 | **2709.84** | **×7.33** | **more conservative** |

Two results worth stating plainly rather than averaging away.

**`segmentation_size` moves the step count 40x and the forecast not at
all.** The static path cancels exactly (§0.6.3). So this correction buys
no accuracy in the static forecast — its value is that the *step count*
is now right, and the step count is what reaches the observation-store
calibration key (§0.6.5b) and the RT1 workload resolver. On the measured
ms/step path, where no cancellation occurs, the same correction changes
the forecast by up to 40x. **No production forecast became more
optimistic:** the static case is exactly neutral and the measured case
was the 40x-conservative one §0.6.3 measured.

**`epochs` is the one that closes real optimism**, and by 7.33x rather
than 10x because only the training phase scales with epochs — inference
and scoring do not. A candidate previously forecast at 369.84 min against
a 60 min budget is now forecast at 2709.84 min. This estimate is
**larger**, which is the routine direction under §1.1.

#### LATENT sites — corrected, but reaching nothing

The VRAM estimator has no production caller (§0.6.2), so these change no
decision. Reported separately so the ACTIVE table is not inflated.

| model | quantity | before | after | note |
|---|---|---|---|---|
| `transformer` | `attention_shape(mt, {})` | `(2, 2)` | **`(4, 2)`** | FU-C-1 closed |
| `transformer` | training peak, absent `seg` | 25,738,880,000 B | **12,877,440,000 B** | `seg` 40000→20000 (÷4 in the quadratic attention term) and `nhead` 2→4 (×2) |
| other five | training peak, absent `seg` | unchanged | unchanged | their declaration already equalled the literal |

#### The property, stated once

For **every** built-in and **both** estimators, an absent key and the
explicitly-declared value now produce byte-identical estimates — measured
ratio `1.0000` across all six models, both phases, both the static and
measured paths. Before B1 that ratio was `0.0250` on the measured
training path and `0.2517` for transformer VRAM.

#### Mutation results

One realistic mutation per corrected site: revert that site to its
pre-B1 literal, alone, and require a test to fail. Anchors are exact
strings asserted to occur exactly once; `__pycache__` is cleared around
every run; the baseline is re-verified after restore.

| # | Site reverted to its pre-B1 literal | round 1 | round 2 |
|---|---|---|---|
| M1 | `attention_shape` `nhead` | CAUGHT | CAUGHT |
| M2 | `attention_shape` `num_layers` | **SURVIVED** | CAUGHT |
| M3 | training VRAM `segmentation_size` | CAUGHT | CAUGHT |
| M4 | training wall-time `segmentation_size` | CAUGHT | CAUGHT |
| M5 | training wall-time `epochs` | CAUGHT | CAUGHT |
| M6 | inference VRAM `segmentation_size` | CAUGHT | CAUGHT |
| M7 | inference wall-time `segmentation_size` | CAUGHT | CAUGHT |
| M8 | wrapper store-reuse `epochs` | **SURVIVED** | CAUGHT |
| M9 | wrapper `segmentation_size` | **SURVIVED** | CAUGHT |
| M10 | wrapper banner `epochs` | **SURVIVED** | CAUGHT |

**Round 1 left four survivors, and they are recorded rather than
quietly re-run.** Each was classified before any test was written —
"add assertions until it goes green" is how a mutation suite stops
meaning anything.

- **M2 — equivalent for built-ins, real gap beyond them.** All three
  config classes declaring `num_layers` declare it as `2`, which is also
  the safety margin, so the mutant is *indistinguishable across the
  entire built-in matrix*. It is only detectable on a generated plugin
  declaring a different depth — which is exactly PR C's constituency,
  and a 6-layer attention model would have been priced at 2. Closed by
  `TestGeneratedPluginDeclarations`, which registers a plugin config
  declaring `nhead=8, num_layers=6`.
- **M8, M9 — real gap.** The wrapper's `seg_size` / `epochs` locals do
  not feed the returned estimate at all (the estimators resolve the
  dicts themselves), so no assertion on `estimated_minutes` or
  `total_train_steps` could ever see them. They feed the
  **observation-store calibration key** and the trigger policy's step
  count. Closed by two tests that capture what the wrapper hands to
  those boundaries.
- **M10 — observability only, pinned anyway.** The wrapper's `epochs`
  local reaches nothing but the printed banner. Classified honestly as
  guarding a **log, not a decision**, and kept because a banner reading
  `epochs=1` for a run that will do ten is the quiet mis-report that
  makes post-mortems expensive.

Round 2: **10 of 10 caught**, baseline green before and after
(`42 passed`). Hygiene: exact-string anchors asserted to occur exactly
once, write-landed assertion, `__pycache__` cleared around every run,
originals restored in a `finally`.

#### Validation at this commit

```text
tests/unit/agent/test_estimator_input_resolution.py     25 passed   (new)
tests/unit/agent/test_estimator_predicates_not_names.py 17 passed   (C3, updated)
tests/unit/agent + core + guardrails + execute_tools    6374 passed, 2 skipped,
                                                        1 xfailed, 290s
ruff check .                                            All checks passed
ruff format --check .                                   758 files already formatted
pyright                                                 0 errors, 4 warnings
```

`0 errors, 4 warnings` matches the `ece24a02` baseline exactly. An
earlier iteration of the resolver produced **8 pyright errors** —
`_usable()` did not narrow `Any | None` for the checker — fixed by
moving the `is not None` test to the call sites, which is clearer than
a `TypeGuard` and needed no `# type: ignore`.

#### Deviations from the approved B1 plan

1. **Scope grew by one file.** `evaluate_time_skill/wrapper.py` was not
   in B1's §2 change list, which named only the two estimators. Its
   three sites belong to the same defect class and one of them corrupts
   the observation-store key, so excluding them would have left the
   class alive — the exact failure Q-B-3 was written to prevent.
2. **`epochs` was not in the approved scope either**, because §0.4 had
   not found it. It is in-class (a config-default vs literal mismatch
   consumed by a resource estimator) and it is the *only* active
   optimistic defect, so omitting it would have made B1 pointless.
3. **The "two paths agree on one literal" criterion was amended**, with
   reasons, in §0.6.7.
4. **No stop-and-escalate was triggered** — a canonical source exists
   for every corrected field.

### 8. Commit boundary

- [ ] Diff touches the two estimators and their tests only
- [ ] No enforcement changes (B3), no breach recording (B2)
- [ ] No new memory or time **terms** — inputs corrected, formulas untouched
- [ ] Diff summary, staged files, tests and deviations shown before commit

---

## Commit B2 — Record realized vs admitted, **semantics-neutral**

### 1. Goal

Close §0.3: make an under-prediction **visible without an OOM**. Today the
system admits a phase against a predicted peak and never looks back, so
the only symptom of a bad forecast is a crash — and a crash is reported as
a crash, not as a broken forecast.

**Why this commit and not another.** It is measurement, not policy, so it
is valid under every candidate semantics in B0 and cannot prejudge
Q-B-1. It also supplies B0 with real breach data.

### 2. Scope

**Changes**
- Wherever the production training and inference phases already capture
  `allocator_peak_mib` / `driver_tree_peak_mib` — **inspect and confirm
  the capture points before writing this list**; §0.3 established the
  fields exist but not that every phase records them.
- The record/manifest surface that will carry the comparison.
- Tests.

**The persisted facts are NEUTRAL — operator correction, §1.1.** Because
Q-B-1 is not frozen until B0, B2 must not encode a policy verdict as a
primitive fact. `budget_breach = true` would already have chosen a
semantics, and B2's whole claim is that it chooses none.

```text
PERSIST (measured facts)          NOT AS A PRIMITIVE FIELD
  admission_estimated_peak_mib      budget_breach
  effective_admission_threshold_mib cap_violation
  realized_peak_mib                 over_budget
  realized_minus_estimated_mib
  realized_minus_threshold_mib
  realized_above_threshold: bool
  measurement_completeness
  owning_process
```

`realized_above_threshold` is a **comparison**, not a verdict — it states
that one measured number exceeded another. After B0 the frozen semantics
interprets the same row as a forecast error (S1), a cap violation (S2), or
a recorded breach/escalation event (S3). **The interpretation belongs in
the human-readable layer, never in the stored fact.**

Note the two deltas are deliberately separate: `realized - estimated` is
**forecast error**, and `realized - threshold` is **headroom consumed**.
They differ whenever the physical cap rather than the operator budget was
binding, and collapsing them would destroy the evidence B0 needs.

**Must remain unchanged**
- **Nothing may be blocked, retried, resized or rejected by this commit.**
  B2 observes. If it changes any admit/refuse outcome, it has become B3
  without the operator's decision.
- Phase ordering, retry semantics, timeout and signal behaviour.
- Existing record fields and their meanings.

**Dependencies:** none. Lands before or after B1 without conflict; B1
first is preferred so the recorded breaches reflect corrected forecasts.

### 3. Implementation plan

- [x] Audit where realized peak is **already** captured per phase — §0.7.
      Answer: **nowhere**. §0.3's premise was half wrong; B2 must add the
      measurement, not only the comparison
- [x] Establish where the **admitted** budget is available at the point
      the realized peak is known — §0.7.3/§0.7.4. Both already meet in
      one scope at the tuner's final-record assembly, so **no state
      threading was needed** and the §12 escalation was not triggered
- [x] Add the comparison and a typed record carrying the **neutral field
      set** — `RealizedVsAdmittedMemory`, both deltas separate, plus
      `binding_constraint`
- [x] **Name every field for what was measured, not for what it means** —
      enforced by a test that fails on any policy-flavoured field name,
      not merely by convention
- [x] Attribute to **the process that caused it** — structurally: the
      counters are read inside the phase's own subprocess and are
      per-process, so a peer cannot inflate them. The recorder accepts no
      PID argument, which is asserted
- [x] Surface it in the record — `final_record["memory"]["realized_vs_admitted"]`,
      per phase

### 4. Validation plan

**Unit**
- [ ] A realized peak below the threshold records
      `realized_above_threshold: False` and correct deltas
- [ ] A realized peak above it records `True` and correct deltas
- [ ] `realized - estimated` and `realized - threshold` differ when the
      physical cap, not the operator budget, was binding
- [ ] **No stored field encodes a policy verdict** — asserted against the
      schema, so a later `budget_breach` field fails the test
- [ ] The binding cap is identified correctly in each of the three regimes
- [ ] Attribution names the owning process/candidate

**Integration / pseudo**
- [ ] A pseudo-mode phase carries the comparison end to end into the
      persisted record
- [ ] **Reachability:** a test that fails if the production path bypasses
      the comparison — the boundary must be *called*, not merely exist

**Negative / invalid input**
- [ ] Realized peak unavailable (measurement incomplete) → recorded as
      **unknown**, never as "within budget". §0.3's classifier already
      distinguishes an incomplete sample from a low one; the same
      distinction must survive here
- [ ] No budget configured (`vram_budget_gb=None`) → no breach, no crash
- [ ] Realized peak of exactly the budget → defined, and documented

**Backward compatibility**
- [ ] Every existing record field unchanged; the addition is additive
- [ ] **No admit/refuse outcome changes anywhere.** Asserted, not assumed

**Real-training Gate:** none for B2 itself. Its output is exercised by B4.

### 5. Acceptance criteria

- For every phase that admits against a budget, the record carries the
  neutral field set — both deltas, the binding cap, completeness and the
  owning process — or an explicit `unknown`.
- **The schema contains no policy term.** S1, S2 and S3 must all be
  expressible as interpretations of the same stored row.
- A synthetic over-budget phase produces a breach record naming the owning
  process.
- **Zero behavioural change to admission**, proven by a test that fails if
  any decision path reads the new field.
- **Mutation, three sites:** removing the comparison; letting an
  unavailable measurement read as "within budget"; and collapsing the two
  deltas into one — each turns a test red.

### 6. Failure and edge cases

| Case | Required behaviour |
|---|---|
| Measurement incomplete | Record **unknown**. Never infer compliance from missing data |
| Phase OOMs before a peak is read | Record the breach as **at least** the last observed value, marked as a lower bound |
| Two candidates co-resident | Attribute per process. A peer's usage is never the candidate's breach |
| No budget configured | No breach; not an error |
| Realized exactly equals admitted | Defined behaviour, documented, tested |
| A future edit bypasses the comparison | The reachability test fails |

### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/core/ -q -k "runtime or admission or measurement"
.venv/bin/python -m pytest tests/unit -q -m "not real_run"
```

- [x] Capture-point audit — §0.7
- [x] Test counts + wall time — §B2.R
- [x] Mutation results — §B2.R

### B2.R — Implementation record, 2026-08-08

**The transport already existed.** §0.7.4 flagged one escalation risk —
that measuring inside the training and inference subprocesses might
require a material architecture change. It does not. The runtime-control
framework already carries a typed, atomic subprocess→parent channel, and
already records a phase's realized **time**; realized **memory** is its
exact analogue and rides the same rails:

```text
train_engine_sandbox.py / inference_single.py
  read_process_peak_mib()                    per-process CUDA counters
  session.record_phase_peak_memory(phase)    mirrors record_phase_actual
    -> PhaseComponentRecord.realized_memory  mirrors .actual_seconds
    -> _write_sidecar()                      atomic, already existed
  -> sandbox_executor._read_runtime_observation_sidecar()   already existed
  -> tuner final_record["runtime_verification"]             already existed
  -> _attach_realized_memory()               ONE new call, extracted
  -> final_record["memory"]["realized_vs_admitted"]
```

No state threading, no singleton, no new runtime mechanism. **§12's
stop-and-escalate was not triggered**, and the phase-6.6 note's "blast
radius" concern turns out to cost two call sites.

**Changed files**

```text
core/runtime_control/records.py          + RealizedPhaseMemory, MemoryCompleteness,
                                           PhaseComponentRecord.realized_memory,
                                           with_realized_memory
core/runtime_control/session.py          + record_phase_peak_memory
core/runtime_control/realized_memory.py  NEW — RealizedVsAdmittedMemory,
                                           realized_vs_admitted,
                                           read_process_peak_mib, reset_process_peak
execute_tools/train_engine_sandbox.py    + capture beside record_phase_actual
execute_tools/inference_single.py        + capture beside record_phase_actual
nodes/.../ml_hyperparameter_tune_agent.py + _attach_realized_memory (extracted)
                                           + one call before _emit_record
tests/unit/core/test_realized_vs_admitted_memory.py   NEW — 24 cases
```

**The tuner's `run()` gained exactly one call.** The decomposition rule
names that function explicitly (2,487 lines, on pyright's complexity
ceiling), so the logic lives in `_attach_realized_memory`, which has its
own inputs, its own failure containment and its own tests.

#### Semantics neutrality, and how it is enforced rather than promised

```text
PERSISTED (measured)                    ABSENT (would freeze Q-B-1)
  admission_estimated_peak_mib            budget_breach
  effective_admission_threshold_mib       cap_violation
  operator_budget_mib / physical_cap_mib  over_budget
  binding_constraint                      penalty / reject
  realized_peak_mib + realized_peak_source
  realized_minus_estimated_mib   FORECAST ERROR
  realized_minus_threshold_mib   HEADROOM CONSUMED
  realized_above_threshold: bool | None
  measurement_completeness
  owning_process_pid
```

`test_no_field_name_encodes_a_verdict` scans both models for
policy vocabulary, so a later `budget_breach` field fails the suite
rather than passing review. `test_all_three_semantics_remain_expressible_from_one_row`
reads the same row three ways (S1 forecast error, S2 cap violation, S3
exceedance magnitude) to show none has been foreclosed.

**The two deltas are separate and a mutation proves it matters** — N3
collapses them and three tests fail. They diverge exactly when the
physical cap rather than the operator budget was binding, which is the
distinction B0 needs to tell "the forecast was wrong" from "the budget
was tight".

#### Missing evidence stays missing

`realized_above_threshold` is `bool | None`, and **`None` means unknown —
never `False`**. A model validator refuses the combination
`realized_peak_mib=None` with any non-null verdict, so the safe reading
cannot be constructed even by accident. `RealizedPhaseMemory` likewise
refuses a `complete` claim with no number, and refuses `unavailable` with
one.

Three completeness states, distinguished rather than merged:
`complete` / `lower_bound` (the last value before the process died; the
true peak is *at least* this) / `unavailable`.

#### Mutation results — 8 of 8 caught, first pass

| # | Mutation | Result |
|---|---|---|
| N1 | remove the production `_attach_realized_memory` call | CAUGHT |
| N2 | let an unavailable measurement read as "within threshold" | CAUGHT |
| N3 | collapse the two deltas into one | CAUGHT |
| N4 | attribute the peak to a peer PID | CAUGHT |
| N5 | drop the training-subprocess capture | CAUGHT |
| N6 | drop the inference-subprocess capture | CAUGHT |
| N7 | rename the comparison to `budget_breach` | CAUGHT |
| N8 | allow a completeness claim with no measurement | CAUGHT |

No survivors, so nothing needed classification. Same hygiene as B1:
exact-string anchors asserted to occur exactly once, write-landed
assertion, `__pycache__` cleared around every run, restore in a `finally`,
baseline green before and after.

#### Validation at this commit

```text
tests/unit/core/test_realized_vs_admitted_memory.py   24 passed  (new)
ruff check . / ruff format --check .                  clean / 760 formatted
pyright                                               0 errors, 4 warnings
```

#### What B2 deliberately did NOT do

- **No policy.** Nothing admits, refuses, retries, resizes or reranks on
  the new field. Asserted two ways: the decision-bearing modules are
  scanned for the name, and `decide_admission` / `assess_total` /
  `complete_setup` are scanned individually.
- **No semantics.** S1, S2 and S3 all remain expressible.
- **No `reset_peak_memory_stats` call in production yet.** The helper
  exists and is documented, but inserting a reset changes what an
  existing counter means for any other reader, so it is left for the
  commit that can prove no other consumer depends on the cumulative
  value. **Consequence, stated rather than hidden:** a recorded phase
  peak is currently the process high-water mark up to the end of that
  phase, which for training includes setup and warm-up. That is an
  over-estimate of the phase's own peak, i.e. the conservative
  direction, and it is exact for the inference subprocess, which does
  one phase. Recorded as a known limitation for B0.

#### Deviations from the approved B2 plan

1. **B2 had to add the measurement, not just the comparison** (§0.7.1).
2. **`physical_cap_gb` is accepted but not yet supplied by the tuner** —
   the admission side does not return the physical cap as a field
   (§0.7.3), so `binding_constraint` resolves to `physical_cap` /
   `operator_budget` from the budget alone and reports `unknown` when
   neither is known. Promoting `cap_note` from a log string to a typed
   field is the clean fix and is left to B3/B0 follow-up rather than
   widened into B2.

### 8. Commit boundary

- [ ] Observation only; no policy, no enforcement
- [ ] No estimator changes (B1)

---

## Commit B0 — Semantics audit and options → OPERATOR FREEZES

> **This commit produces a written operator decision, not code.** It is
> numbered B0 because it *gates* B3, and placed here because it is
> strongest when it can cite B1's corrected forecasts and B2's real
> breach data.

### 1. Goal

Answer Q-B-1 with evidence, so that the name, the schema field and the
runtime behaviour can be made to agree — in that order, and only after the
operator has said which of them is right.

### 2. Scope

This document plus `docs/design/v21_priorities.md`. **No production code.**

**Dependencies:** B1 and B2 landed, so the audit can cite measured
behaviour rather than V20's three OOMs alone.

### 3. Implementation plan

- [ ] Re-run §0.1's determination against the current head: which
      enforcement posture do the production launchers actually set, and
      what does each value do
- [ ] Enumerate every consumer of `vram_budget_gb`,
      `gpu_pair_ceiling_gib` and `gpu_admission_enforcement`, and state
      for each whether it treats the number as a forecast bound or a usage
      bound
- [ ] Present B2's measured breach distribution — how often, how far, and
      whether B1's corrections removed the breaches or merely shrank them
- [ ] Write the options with their consequences (below), and **stop**

### 4. The options, stated now so the operator can see the shape

Not a recommendation. Each is internally consistent; they differ in what
they promise and what they cost.

| | Semantics | What "12 GiB" then means | Cost |
|---|---|---|---|
| **S1** | **Admission estimate** (today's behaviour, honestly named) | "no candidate is *admitted* whose predicted peak exceeds 12 GiB" | Cheapest and already true. Promises nothing about realized usage, so OOMs remain possible and the schema/CLI wording must change to stop implying a cap |
| **S2** | **Enforced cap** | "no candidate *uses* more than 12 GiB" | Requires a runtime mechanism (the mechanism is B3's output, not chosen here). Strongest promise; highest risk of killing legitimate work when the forecast is merely imprecise |
| **S3** | **Admission estimate + recorded breach + operator-visible escalation** | "admitted on a forecast, and every breach is recorded and surfaced" | B2 already builds the measurement half. Middle cost; makes forecast error a tracked quantity rather than a surprise |

**What the audit already tells us about the choice.** §0.1 and §0.2
together mean V20 did not fail because enforcement was absent — it
enforced a forecast that was wrong. If B1 shows the forecast was wrong
*because of §0.4's mismatches*, S1 or S3 may be sufficient and S2 may be
solving the wrong problem. **If B1 does not close the gap, that is
evidence for S2.** This is why B0 sits after B1 and B2.

### 5. Acceptance criteria

- A written operator decision naming **one** of S1/S2/S3, recorded in this
  document and in the V21 ledger with its date.
- Every consumer enumerated with its current interpretation.
- B2's breach data presented with counts and magnitudes, not adjectives.

### 6. Failure and edge cases

| Case | Behaviour |
|---|---|
| The operator picks none of S1/S2/S3 | Their alternative is the decision; record it verbatim and re-plan B3 |
| B1 fully closes the breach | Record it. It is a legitimate outcome and makes S2 harder to justify |
| Consumers disagree about the meaning today | That *is* the finding. Enumerate the disagreement rather than picking a winner |

### 7. Verification commands and evidence

- [ ] Consumer enumeration — **to record**
- [ ] Breach distribution from B2 — **to record**
- [ ] The operator's written decision — **to record, with date**

### 8. Commit boundary

- [ ] Documentation only

---

## Commit B3 — Enforcement consistent with the frozen semantics

> **BLOCKED on Q-B-1. This section is deliberately a plan for producing a
> plan.** Part III: *"This PR must not pre-commit to an enforcement
> mechanism. Whether the answer is dynamic enforcement, a watchdog,
> re-measurement, pair/aggregate accounting over concurrent phases, or
> admission-envelope semantics with honest reporting is an **output** of
> the audit, not an input."*

### 1. Goal

Make the runtime behaviour, the schema field and the operator-facing name
agree with whichever semantics B0 froze.

### 2. Scope

**Unknown until Q-B-1 is answered**, and stating it now would be the
pre-commitment Part III forbids. What *is* fixed:

**Must remain unchanged regardless of the answer**
- The metric, the scorer, every score.
- Retry, phase order, signal and timeout semantics.
- B1's corrected forecasts and C3's property-derived predicates.
- Attribution: a breach belongs to the process that caused it.

**Dependencies:** B0's written decision. **B3 is not written until then.**

### 3. Implementation plan

- [ ] Receive the frozen semantics from B0
- [ ] **Return to this document and write B3's real §2-§8** to the same
      standard as B1 and B2, with its own audit performed first
- [ ] Obtain approval for that plan before implementing

### 4-8

**Deliberately empty.** Filling them now would be inventing the mechanism
the operator has not yet chosen.

---

## Commit B4a — Gate rungs 1-2 (no GPU, then no training)

### 1. Goal

Prove the frozen semantics behaves correctly on *reconstructed* numbers
before any real resource is consumed. Part III: **real training is never
the discovery tool.**

### 2. Scope

Tests and evidence. **Dependencies:** B3.

### 3. Implementation plan

- [ ] **Rung 1 — synthetic accounting, no GPU.** Replay attempt 3's
      observed numbers (17.46 + 13.45 GiB against 149 MiB free) and assert
      the intended admit/refuse decision under the frozen semantics
- [ ] **Rung 2 — controlled allocator holder.** A process holding a known
      CUDA reservation, **no model and no training**, confirming detection
      and attribution. The reservation is the independent variable, which
      a training run can never be

### 4. Validation plan

- [ ] Rung 1: the decision matches the frozen semantics for each replayed
      configuration, including the boundary
- [ ] Rung 2: the breach is detected, and attributed to the holder
- [ ] Rung 2: a **peer** process is not blamed — the explicit P6.4 rule
- [ ] Each rung passes **before** the next is attempted

### 5. Acceptance criteria

- Rung 1 reproduces attempt 3's inputs exactly, cited by value.
- Rung 2 detects and attributes a reservation of known size with no model
  loaded.
- No GPU is used in rung 1; no training in rung 2.

### 6. Failure and edge cases

| Case | Behaviour |
|---|---|
| Rung 1 disagrees with the frozen semantics | The implementation is wrong, or the semantics was under-specified. Stop; do not proceed to rung 2 |
| CUDA unavailable for rung 2 | Skip **loudly** with a reason; never silently pass |
| Detection attributes to a peer | **Gate fails** — that is the property under test |

### 7. Verification commands and evidence

- [ ] Rung 1 replay inputs and decisions — **to record**
- [ ] Rung 2 reservation size, detection, attribution — **to record**

### 8. Commit boundary

- [ ] Tests and evidence only

---

## Commit B4b — Gate rungs 3-4 (production path, then minimal real)

### 1. Goal

Confirm the production admission path actually consults the mechanism, and
then demonstrate the behaviour once on real hardware.

> **Rung 4 is a real-GPU run.** Its readiness packet — exact command,
> bounds, expected artifacts and stop conditions — is written into this
> document **before** it is launched, as PR C's C5b did.

### 2. Scope

Tests and evidence. **Dependencies:** B4a passed.

### 3. Implementation plan

- [ ] **Rung 3.** A test proving the production admission path consults
      the aggregate, failing if a future edit bypasses it. Reachability,
      not existence — PR C's repeated lesson
- [ ] **Rung 4.** The **smallest** real co-residency run that demonstrates
      the behaviour. Explicitly **not** two full scientific chains and
      **not** a deliberate card-exhaustion campaign
- [ ] Record the readiness packet before launching

### 4. Validation plan

- [ ] Rung 3 fails when the production path is edited to bypass the check
- [ ] Rung 4: the breach is detected and correctly attributed live
- [ ] Rung 4: **no peer-caused rejection** occurs

### 5. Acceptance criteria

- Rung 3's reachability test fails under a bypass mutation.
- Rung 4 demonstrates detection **and** attribution in a live two-chain
  run, at the smallest scale that can show it.
- Any step not run is recorded as not run, with the reason. **Never
  claimed as passed.**

### 6. Failure and edge cases

| Case | Behaviour |
|---|---|
| A real run OOMs before demonstrating the behaviour | Record it; that is data about the mechanism, not a reason to enlarge the run |
| A scientific outcome (bad score, collapse) | **Irrelevant to PR B.** Record and move on — PR C's C5b rule |
| The behaviour does not reproduce at minimal scale | Record it. Do **not** escalate to a card-exhaustion campaign to force it |
| Concurrency interacts with `max_active` (§0.5) | Expected territory for PR B; record and diagnose |

### 7. Verification commands and evidence

- [ ] Rung 3 mutation result — **to record**
- [ ] Rung 4 command, bounds, artifacts — **to record before launching**
- [ ] Wall time, GPU time, observed peaks — **to record**

### 8. Commit boundary

- [ ] Evidence only; any defect found gets its own commit

---

## 2. Merge checklist — what PR B must prove

- [ ] **1. FORECAST INPUTS MATCH DECLARATIONS** — every estimator fallback
      agrees with its canonical source or is documented as deliberately
      different; no estimate more optimistic; C3's property-derived
      guarantee intact (B1)
- [ ] **2. UNDER-PREDICTION IS VISIBLE WITHOUT AN OOM** — realized phase
      memory is recorded against the admitted budget, with attribution to
      the causing process (B2)
- [ ] **3. THE SEMANTICS IS FROZEN IN WRITING** — one of S1/S2/S3 (or the
      operator's alternative), dated, in this document and the ledger (B0)
- [ ] **4. NAME, SCHEMA AND BEHAVIOUR AGREE** with that semantics (B3)
- [ ] **5. THE LADDER WAS CLIMBED IN ORDER** — rungs 1→4, each green
      before the next was attempted, real training never the discovery
      tool (B4a, B4b)
- [ ] **6. NO PEER-CAUSED REJECTION** — contention is never candidate
      evidence (B4)

### What PR B is explicitly NOT required to do

- Raise or lower any threshold without measured justification.
- Change `max_active` policy before the audit.
- Choose an enforcement mechanism before the semantics is frozen.
- Fix PR G's inference-throughput batch selection.
- Reach a good score in any Gate. **Scientific outcomes are not PR B
  acceptance criteria** — the C5b rule carries forward.

---

## 3. PR-level review template

Filled at completion, per Part III §E.7 — the `v20_priorities.md` §20.11
fields plus the five V21-specific lines.

---

## 4. Operator rulings — RESOLVED 2026-08-08

Full text in §1.1. Summary and status:

- [x] **Q-B-1 — DEFERRED BY DESIGN.** Do not choose S1/S2/S3 yet. It
      blocks **B3 only**, not B1 or B2. Order:
      `B1 → B2 → B0 evidence review → operator freezes → write B3`.
      Operator's prior is **S3**, explicitly not frozen; B1/B2 evidence
      decides. **The earlier line "no implementation begins until Q-B-1 is
      resolved" was wrong and is removed.**
- [x] **Q-B-2 — YES.** B1 is authorised to change built-in estimates where
      audit proves a fallback contradicts the canonical value. C3's
      byte-parity constraint is lifted **for this bounded class only**.
      Per changed cell: canonical source, previous value, corrected value,
      magnitude, direction, production reachability. **Input facts may
      change; the estimator's model may not.** C3's guard is updated, not
      deleted.
- [x] **Q-B-3 — YES.** The `segmentation_size` mismatches are in B1.
      Sweep bounded to config/default inputs consumed by the two resource
      estimators; not a repository-wide cleanup.

### Two defects in this document, fixed

- [x] **The "never more optimistic" rule contradicted B1's own goal.** It
      required every fallback to match its canonical source *and* no
      estimate ever to shrink — impossible for `transformer`
      `segmentation_size` 40000 → 20000. Held absolutely it would have
      preserved a value known to be false while calling it a config
      fallback. Replaced with *"no estimate may become more optimistic
      accidentally, silently, or without evidence"*, plus the explicit
      procedure for a justified decrease (§1.1).
- [x] **B2 was not actually semantics-neutral.** It spoke of recording a
      *breach*, which presumes S2/S3. Rewritten to persist measured facts
      only, with `realized_above_threshold` as a comparison rather than a
      verdict, and the two deltas kept separate.

**Cleared to begin B1, then B2. STOP for operator review at B0 before
writing B3.**
