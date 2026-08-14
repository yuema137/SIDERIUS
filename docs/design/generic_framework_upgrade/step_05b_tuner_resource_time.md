# Step 05b — Tuner resource & time planning — detailed design

Part of **Step 05** (roadmap §15 step 5, §7d). Step 05's three submodule
designs jointly constitute the Step-05 acceptance entry (roadmap §19); the
Step-level completion contract lives in roadmap **§15.1a**.

| Field | Value |
|---|---|
| Status | **DRAFT — READY FOR OPERATOR REVIEW. Not frozen. Implementation NOT authorized.** |
| Design base | `13b08550` |
| Depends on | **Step 02** (Dataset Profile) · **Step 03** (`ModelIOContract`) · **Step 04a** (`model_io_probe_skill`, the shared probe-realization authority) |
| Blocks | nothing — see §7 |
| Roadmap row | §15.1 `§7d Tuner resource/time planning` |

---

## 0. Source audit — what changed since the roadmap wrote §7d

Two findings materially re-scope this PR, one shrinking it and one giving it
a consumer the roadmap could not have predicted.

```text
Previous assumption (roadmap §7d):
  "Couplings: ×256 logits/one-hot terms; PSD-unit
   `PSD_SEGMENT_LENGTH // seg_size` in 5+ places; seg defaults 40000/1000."

Audit evidence at 13b08550:
  The PSD-unit term is ALREADY derived from the Dataset Profile:
    execute_tools/workload_resolvers.py:36,49,139  -> resolve_dataset_profile()
    agent/skills/evaluate_time_skill/wrapper.py:65,92,357,767 -> same
  It is derived, but AMBIENTLY: the shape is
  `profile = profile or resolve_dataset_profile()`, an optional parameter
  with a singleton fallback — the same defect shape Step 02b removed from
  tuner selection.

  The `40_000` seg fallbacks are NOT mainly §7d's: they live in
    core/runtime_control/gpu_measurement_identity.py:214
    core/runtime_control/gpu_measurement_worker_main.py:254
    core/runtime_control/probe_production.py:220
    core/runtime_control/campaign.py (fixture roster)
  i.e. §7e measurement/verification — assigned to STEP 07, not Step 05.

Corrected understanding:
  §7d's PSD-unit work is largely done; what remains is converting ambient
  fallback into required injection. The seg-fallback item is an AUDIT
  obligation here and a FIX obligation mostly in Step 07.
```

```text
New evidence the roadmap could not have (Step 04a landed after it):
  Step 04a created agent/skills/model_io_probe_skill.py — ONE shared
  probe-realization authority (`build_model_input`, `build_loss_probe_pair`,
  `realize_shape`, `expected_output_shape`).

  Its production consumers today are exactly TWO:
    nodes/ml_model_implementor/ml_model_implementor.py:38
    nodes/ml_code_validator_agent/ml_code_validator_agent.py:56

  The LIVE VRAM probe does NOT use it and still builds TIDMAD-shaped
  tensors inline:
    agent/skills/evaluate_vram_skill/wrapper.py:248
        tgt = torch.zeros((batch_size, 256, seg_size), dtype=target_dtype)
    plus [B, 256, T] reasoning at :90, :196-205, :236 and
    batch_resolver.py:85.

Implementation consequence:
  05b's strongest capability is making the live resource gate the THIRD
  consumer of the existing probe authority. This is not a new seam — the
  authority exists, is proven by 04a's ladder, and this PR supplies a
  real production consumer for it.
```

## 1. Observable final capability

> The tuner's **resource and time forecasts derive their task-shaped terms**
> — class/logit extent, decomposition (PSD) unit, and probe tensor shapes —
> from the authorities that already own them, instead of from literals
> inlined in the estimators. **Calibration and runtime values keep their
> current owners and current values**, and remain separately identifiable as
> calibration rather than task configuration.

**The authority split is precise, and no single authority is a general
"resource semantics" owner:**

| Fact | Authority |
|---|---|
| model/probe tensor **realization** | Step-04a `model_io_probe_skill` — a probe-realization **consumer seam**, nothing more |
| Model-I/O facts (class extent, output shape, decode rule) | **Step-03 `ModelIOContract`** |
| PSD / decomposition topology | **Step-02 `DatasetProfile`** |
| resource **calibration** (ratios, caps, batch table, overheads) | the existing calibration/runtime authority — unchanged |
| hardware capacity and operator budgets | the existing runtime **Hardware Context** / operator authority — unchanged |

It is wrong to say resource terms derive "through `model_io_probe_skill`":
the skill *realizes probe tensors* from a contract. The contract facts come
from Step 03, the topology from Step 02, and the calibration and hardware
facts from neither.

**Deliberately NOT claimed:**

- not that resource *policy* changes — admission thresholds, retry and
  refusal semantics are untouched;
- not that calibration becomes generic or configurable;
- not measurement/verification identity (§7e → Step 07);
- not metric, planner or execution genericity.

## 2. The classification that governs this PR

The single most important discipline here: **a constant is not task
configuration merely because it is a constant.**

| Value | Site | Class | Disposition |
|---|---|---|---|
| `256` in probe targets | `evaluate_vram_skill/wrapper.py:248`, `:196-205`; `batch_resolver.py:85` | **TASK-SHAPED TERM** — the contract's class axis | **DERIVE** via `model_io_probe_skill` |
| `PSD_SEGMENT_LENGTH // seg_size` | `workload_resolvers.py:129`; `evaluate_time_skill/wrapper.py:92,357,767` | **TASK-SHAPED TERM** | already DERIVE — **tighten** ambient→injected |
| `_INFERENCE_VS_TRAINING_RATIO = 2.7` | `inference_skill/estimator.py:79` | **CALIBRATION** — empirical median, measurement table at `:69-74` | **KEEP CALIBRATION**, value unchanged |
| `_MAX_BATCH_TIMESTEPS = 800_000` | `evaluate_vram_skill/compute_intensity.py:40` | **CALIBRATION/RUNTIME cap** | **KEEP**, unchanged |
| batch candidate table (64…1) | `evaluate_vram_skill` | **CALIBRATION** | **KEEP**, unchanged |
| RSS caps 40/60/24 GiB, overheads | `core/sandbox_executor.py:114` etc. | **RUNTIME limits** | **KEEP** — and note CLAUDE.md pins the 60 GiB inference cap |
| `SEG_SIZE_BOUNDS = (2500, 40_000)` | `evaluate_time_skill/trigger_policy.py:34` | **CALIBRATION trigger policy** | **KEEP** — audit only |
| `segmentation_size` `40_000` fallbacks | `core/runtime_control/*` | **§7e — STEP 07 owned** | **AUDIT + RECORD**, do not fix here |

**Migrating any calibration value into task config is a stop condition.**

## 3. Seg-size fallback resolution (the §14 row's obligation)

The §14 ledger leaves *"Seg-size fallback defaults (40000/1000) … audit in
§7d design."* This design discharges that audit:

| Fallback | Meaning from source | Disposition |
|---|---|---|
| `model_config.get("segmentation_size", 40_000)` in `gpu_measurement_identity.py:214`, `gpu_measurement_worker_main.py:254`, `probe_production.py:220` | **planned-identity default** — a stand-in so a measurement identity can be keyed when the plan omits the field | **§7e / Step 07 owned.** Record; do not fix in Step 05 |
| `SEG_SIZE_BOUNDS` upper bound `40_000` | **calibration trigger policy** — when warm-up is required | **KEEP CALIBRATION** |
| `campaign.py` `40000` entries | **fixture roster** for a calibration campaign | **KEEP — test/campaign data** |

**Finding: there is no single semantic behind "40000".** The numbers
coincide because TIDMAD's usable segmentation happens to sit there. Per the
kickoff's own rule — *do not merge different defaults merely because the
numbers look related* — they stay separate and are **not** unified into one
resolver. The §14 row should be updated to record this, not to create the
"`§7d` resolver" it speculatively named.

## 4. Dead vs live estimators

The roadmap flagged analytic estimators as *"partly production-dead"*.
Implementation must classify **each** estimator before touching it:

```text
production live | diagnostic only | test-only | dead | fallback
```

**Binding rule for this PR**: an estimator that is dead or diagnostic-only is
**not** genericized. It is either left alone or recorded for a later cleanup.
Deriving a task term into a dead code path creates an abstraction whose only
consumer is dead code — a §0-rule-8 violation wearing a Step-05 badge. The
live surfaces this PR targets are the **VRAM probe / batch resolver** and the
**time aggregator**, both of which gate real admission decisions.

## 5. Upstream authorities / first production consumer

Consumes Step 02's `DatasetProfile`, Step 03's `ModelIOContract`, and Step
04a's `model_io_probe_skill`. **First production consumer: the live VRAM
probe and batch resolver** — the gate that admits or refuses a real attempt.
This is a consumer that exists and runs today.

## 6. Stage-A compatibility surfaces

| Surface | Criterion | Oracle status |
|---|---|---|
| forecast breakdowns (train/inference/scoring) | **deep-equal** under TIDMAD | EXISTING (PR-G parity-pin pattern) |
| admission/refusal decisions and their identities | **identical** | EXISTING |
| resolved batch size per candidate | **identical** | EXISTING but possibly **too low-level** — classify at Checkpoint 0 |
| probe tensor shapes/dtypes actually built | **identical** under TIDMAD | **MISSING — Checkpoint 0 captures it** |
| calibration constants | **unchanged values** | assert by pin |

## 7. Dependencies

Depends on Steps 02, 03, 04a — all merged. **Independent of 05a**: it
consumes `SampleSet` *values*, whose shape 05a is required to leave
byte-identical. **Independent of 05c.** Order is preference, not blocking.

## 8. Stage-B atomic contrast

**One axis: a single task-derived workload term, with calibration,
hardware and policy held fixed.**

Concretely: a contrast contract whose class extent differs from 256 must move
the derived probe shape and the forecast term that depends on it — while
`2.7`, the intensity cap, the batch table and the hardware context stay
byte-identical. Reds when a `256` survives in a live estimator.

Do **not** build a contrast that varies topology *and* class count *and*
calibration at once.

## 9. Checkpoint C — live integration

A **real production VRAM/time gate prices and admits a real attempt** using
derived terms — the actual gate, not a helper. Under TIDMAD the decision and
breakdown are unchanged; under the contrast contract the derived terms move
and the calibration values do not.

Deterministic where the probe can be stubbed at its measurement boundary. If
the live probe cannot be exercised without a GPU, that is a **Gate-2 trigger
question** (§11), not a reason to weaken Checkpoint C into a helper test.

## 10. Failure classes

1. A calibration constant is migrated into task config → the framework
   silently claims empirical values are task declarations.
2. A **dead** estimator is genericized → consumer-less abstraction.
3. A derived term changes a TIDMAD forecast by even one unit → admission
   behavior shifts; every downstream attempt is priced differently.
4. Ambient re-resolution (`profile or resolve_dataset_profile()`) is left in
   place → a run bound to a contrast profile prices against the ambient one.
5. Probe realization is duplicated instead of delegated to
   `model_io_probe_skill` → a **second** probe authority, undoing 04a.

## 11. Gates

| Gate | Decision | Rationale / flip |
|---|---|---|
| **Gate 1** | **NOT REQUIRED** | no LLM-visible surface. **Flip**: if a resource literal reaches a prompt (cf. OD-S4-1's implementor capacity prose) |
| **Gate 2** | **CONDITIONAL — semantic rule below** | The changed surface **decides whether real attempts run**, and failure class 3 is not observable from a stubbed probe alone |

**The condition is semantic:**

```text
Checkpoint C must prove the LIVE production admission/pricing decision.

  deterministic production-path evidence fully exercises that decision
      -> Gate 2 NOT REQUIRED

  otherwise
      -> Gate 2 REQUIRED, under the CURRENT gate_testing_standard.md
```

Which branch holds is settled by implementation-time source evidence, not by
preference. Gate **launch choreography** — exact timing, exact bounded
command, and cost projection within the normal autonomous validation budget —
belongs to the Implementation Working Rules and current Gate policy, **not**
to this design and **not** to the operator's design review.

## 12. Validation budget

Checkpoint 0 probe-shape capture → focused derivation tests → calibration
"unchanged value" pins → dead/live estimator classification recorded →
Stage-B rung → Checkpoint C → **bounded Gate 2 if and only if §11's
condition holds** → exact-head CI. No local full suite. No real LLM.

## 13. Rollback boundary

`agent/skills/evaluate_vram_skill/`, `agent/skills/evaluate_time_skill/`,
`execute_tools/workload_resolvers.py`, and directly affected tests.
**`core/runtime_control/` measurement identity is NOT touched** (Step 07).

## 14. Convergence-ledger implications

- **Model I/O contract / ForwardContract** — 05b adds a *third* production
  consumer of the probe authority. Disposition stays **RECORD ONLY**
  (OD-S4-4); a third consumer is more evidence for the recorded split, not a
  reason to merge the two representations.
- **Seg-size fallback defaults** — resolved in §3: **no single semantic; do
  not unify.** The row should record this and close, replacing its
  speculative "`§7d` resolver" owner.
- **SampleSet type + JSON key coercion** — 05b is the closest candidate for
  the "one consumer design" the row awaits, since `resolve_*_workload` reads
  SampleSets directly. Record the evidence; **do not** build the typed
  wrapper. Default remains RECORD FIRST.

## 15. Stop conditions

- A task term cannot be derived without inventing a new config field → STOP.
- Deriving a term changes a TIDMAD forecast → STOP; that is a defect.
- The work requires touching `core/runtime_control` measurement identity →
  STOP (Step 07).
- A calibration record store is required to migrate a constant → STOP; the
  roadmap defers calibration records, and this PR has no such consumer.

## 16. Implementation milestones (semantic)

1. Checkpoint 0: probe-shape capture; classify every estimator live/dead.
2. Route probe realization through `model_io_probe_skill` (live sites only).
3. Convert ambient profile fallback to required injection in the live path.
4. Calibration pins + the §3 seg-fallback audit record.
5. Stage-B rung, Checkpoint C, and the Gate-2 condition decision.

## 17. Implementation ledger

*(empty — populated at implementation kickoff)*

## 18. Remaining operator decisions

**NONE.** Every question here is resolved from source: the classification
table (§2) by the constants' documented derivations, the seg-fallback
disposition (§3) by the sites' differing meanings, and the Gate disposition
(§11) by a semantic condition that implementation evidence settles.

## 19. Configuration-architecture preservation (Step-05 cross-cutting invariant)

Binding for this PR (roadmap §15.1a). **Ambient → injected derivation does
NOT mean copying authorities into persisted configuration.** The required
architecture is:

```text
already-resolved DatasetProfile / ModelIOContract
    -> runtime typed/function transport
    -> resource consumer
```

Explicitly forbidden without a MATERIAL STOP and design review:

- a `dataset_profile` copy inside train config;
- a `model_io` copy inside resource config;
- a new persisted workload-term config;
- any new user-facing configuration hierarchy for resource terms.

Frozen compatibility:

| Surface | 05b effect |
|---|---|
| model config | **unchanged — legacy loads** |
| loss config | **unchanged — legacy loads** |
| train config | **unchanged — legacy loads** |
| `TrialConfig` / tuner config | **unchanged** |
| calibration constants | **values unchanged**, ownership unchanged |
| CLI / argv | **unchanged**, unless the current resource boundary already differs — recorded if so |
| historical run replay | **preserved — no migration required** |

Stage-A property: *a representative historical TIDMAD serialized
configuration loads under post-05b code without migration and resolves to the
same effective model/loss/train/tuner semantics*, provable by deterministic
config resolution.

If implementation proves a new field is genuinely unavoidable, that is a
**MATERIAL STOP**, not permission to widen the config system.
