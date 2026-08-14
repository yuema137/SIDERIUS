# Step 05b — Tuner resource & time planning — detailed design

Part of **Step 05** (roadmap §15 step 5, §7d). Step 05's three submodule
designs jointly constitute the Step-05 acceptance entry (roadmap §19); the
Step-level completion contract lives in roadmap **§15.1a**.

| Field | Value |
|---|---|
| Status | **DRAFT — REVISION 2. Not frozen. Implementation NOT authorized.** |
| Design base | **re-anchored to `82a548f8`** (master after 05a merged as `cfb3b1c7`). Revision 1 was written against `13b08550`; every source citation below has been re-verified and moved where it moved (§0.3) |
| Depends on | **Step 02** (Dataset Profile) · **Step 03** (`ModelIOContract`) · **Step 04a** (`model_io_probe_skill`, the shared probe-realization authority) |
| Blocks | nothing — see §7 |
| Roadmap row | §15.1 `§7d Tuner resource/time planning` |
| Decomposition | **ONE PR**, nine semantic commits C0-C8 (§16). No child design doc |
| Operator decisions carried into rev 2 | **OD-05b-1** probe scope = *parameterize the 04a realizer additively* (§0.2 option A) · **OD-05b-2** re-anchor all citations to current master |

> **Revision 2 exists because revision 1's central claim did not survive
> source audit.** §0.2 records what was checked, what was found, and what the
> operator decided. Read it before §1.

---

## 0. Source audit — what changed since the roadmap wrote §7d

Two findings materially re-scope this PR, one shrinking it and one giving it
a consumer the roadmap could not have predicted.

> **The two blocks below are revision 1's evidence, at base `13b08550`, kept
> unedited so the audit chronology survives.** Several of their line numbers
> are stale at `82a548f8`; **§0.3 is the corrected anchor table** and is what
> implementation should read. Do not act on the numbers inside these blocks.

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
    nodes/ml_model_implementor/ml_model_implementor.py:1840, :1995
    nodes/ml_code_validator_agent/ml_code_validator_agent.py:646
  and both receive the contract as an OPTIONAL parameter
  (`model_io_contract: ModelIOContract | None = None`) with a documented
  legacy fallback when it is absent.

  The LIVE VRAM probe does NOT use it and still builds TIDMAD-shaped
  tensors inline:
    agent/skills/evaluate_vram_skill/wrapper.py:248
        tgt = torch.zeros((batch_size, 256, seg_size), dtype=target_dtype)
    plus [B, 256, T] reasoning at :90, :196-205, :236 and
    batch_resolver.py:85.

Implementation consequence:
  05b's strongest capability is making the live resource gate the THIRD
  consumer of the existing probe authority.
```

### 0.2 What revision 1 got wrong — and the operator decision that resolves it

Revision 1 closed the passage above with *"This is not a new seam — the
authority exists, is proven by 04a's ladder, and this PR supplies a real
production consumer for it."* **Source audit at `82a548f8` refutes that on
two counts.** Both were found before any implementation planning, which is
why they change the design rather than surfacing mid-PR.

```text
Previous assumption (rev 1 §0):
  the VRAM gate can simply CALL the 04a authority; no new seam is needed.

Audit evidence at 82a548f8:

  (1) The 04a authority realizes at VALIDATION-PROBE extents, not at the
      candidate's extents. `realize_shape` is unparameterized
      (model_io_probe_skill.py:109-140):
          batch-role axis   -> PROBE_BATCH            = 1     (:68)
          symbolic/dynamic  -> PROBE_SYMBOLIC_EXTENT  = 64    (:75)
      and `build_loss_probe_pair` uses LOSS_PROBE_BATCH = 2 (:293),
      LOSS_PROBE_LENGTH = 100 (:294).
      The VRAM gate must build its target at the candidate's REAL
      batch_size and seg_size — that is the entire content of a capacity
      measurement. So `build_model_input` / `build_loss_probe_pair` cannot
      be consumed verbatim by this path.

  (2) No ModelIOContract reaches the VRAM gate today, and no plumbing
      exists to carry one. `evaluate_vram_skill/wrapper.py` imports no
      model-io module at all (:40-74); it receives `model_type` and derives
      the target shape from `get_output_type(model_type)` (:229). The tuner
      input schema carries no contract either — `grep model_io` over
      agent/schemas/hyperparam_tuning.py returns nothing.

  (3) The production pre-flight runs in a CHILD PROCESS
      (`run_production_preflight`, preflight_adapter.py:212 -> IsolatedProbeSpec
      -> preflight_worker_main.py:190), so any contract must cross a process
      boundary as well as a function boundary.

Corrected understanding:
  the probe half of 05b is a real seam extension, not a call. It needs
  (a) a way to realize declared shapes at caller-supplied extents, and
  (b) a contract transport to the resource path, in-process and across the
  pre-flight worker boundary.
```

**Operator decision OD-05b-1 — option A, "parameterize the 04a realizer".**

```text
model_io_probe_skill.py   (Step-04a owned; change is ADDITIVE + DEFAULTED)
    realize_shape(tensor, *, batch=None, symbolic=None)
        batch    or PROBE_BATCH            # omitted -> byte-identical
        symbolic or PROBE_SYMBOLIC_EXTENT  # to every existing caller

evaluate_vram_skill/wrapper.py
    _build_probe_tensors(..., model_io_contract=None)
        contract present -> realize_shape(declared_output_tensor(...),
                                batch=batch_size, symbolic=seg_size)
        contract absent  -> today's [B, 256, T]      (unchanged)

transport: tuner -> run_production_preflight -> IsolatedProbeSpec
           -> spec.json -> preflight_worker_main -> run_skill
```

Rejected alternatives, recorded so the choice is auditable:

| Option | Why not |
|---|---|
| **B** — derive only the class extent, keep local tensor construction | leaves rank and axis order hardcoded in the resource path, i.e. a *second* shape-realization site. That is this design's own failure class 5 (§10) |
| **C** — drop the probe half; ship only the profile tightening | smallest and safest, but 05b would deliver no Model-I/O capability at all and §7d's `×256` coupling would stay open with no owner |

**Why the additive parameterization is safe.** Both new keyword arguments
default to the existing module constants, so every current call site
(`build_model_input`, `expected_output_shape`, and the two node consumers)
resolves the identical shape it resolves today. A defaulted keyword cannot
change an existing caller's behaviour, and C1's acceptance criteria pin that
as a byte-equality assertion rather than an argument.

**Precedent for the transport.** A file-based `ModelIOContract` transport
already exists for the training subprocess — `train_engine_sandbox.py:1249`
declares `--model_io_json` and loads it with `load_model_io_contract`
(`agent/schemas/model_io_contract.py:312`). C3 follows that established
pattern rather than inventing one, and the pre-flight worker already receives
its inputs as a JSON spec (`IsolatedProbeSpec`, isolated_probe.py:168-182),
so the addition is one optional field beside `model_config_payload`,
`train_config` and `loss_config`.

### 0.3 Citation re-anchoring (OD-05b-2)

Revision 1 cited `13b08550`. Every site has been re-verified at `82a548f8`:

| Rev-1 citation | Status at `82a548f8` |
|---|---|
| `workload_resolvers.py:36,49,139` ambient fallback | **corrected** — the fallbacks are `:49` (in `_validate_seg`) and `:139` (in `resolve_inference_workload`). `:36` is the import line, not a fallback |
| `workload_resolvers.py:129` PSD-unit | **corrected** — the PSD unit is computed at `:50`; `:157` uses `psd_segment_length` for output bytes |
| `evaluate_time_skill/wrapper.py:65,92,357,767` | **corrected** — ambient reads are at `:92`, `:357`, `:767`. There is no ambient read at `:65` |
| `evaluate_vram_skill/wrapper.py:248` target literal | **confirmed unchanged**; the enclosing helper is `_build_probe_tensors` (`:176`), called once at `:588` |
| `inference_skill/estimator.py:79` ratio | **confirmed unchanged**; its ambient fallback is `:208` |
| `compute_intensity.py:40` `_MAX_BATCH_TIMESTEPS` | **confirmed unchanged** |
| `trigger_policy.py:34` `SEG_SIZE_BOUNDS` | **confirmed unchanged** |
| `core/sandbox_executor.py:114` RSS caps | **moved to `:121`** (`_ROLE_DEFAULT_RSS_GB`) |
| `core/runtime_control/*` seg fallbacks | **confirmed**: `gpu_measurement_identity.py:214`, `gpu_measurement_worker_main.py:254`, `probe_production.py:220` |
| probe-skill consumers `implementor:38`, `validator:56` | **corrected** — those are import lines; the call sites are `implementor:1840,:1995` and `validator:646` |

Implementation must still re-enumerate (the 05a precedent: line numbers drift,
capabilities do not). These anchors are reading aids, not contracts.

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

**Honest scope of the probe half (rev 2).** 05b does not merely *call* the
04a authority — it **extends** it, additively, so that one realization
authority can serve both validation-probe extents and capacity-probe extents
(§0.2). The capability claim is therefore:

> the live resource gate realizes its probe target from the **declared
> Model-I/O contract** — rank, axis order and the class extent — at the
> **candidate's own** batch and segment extents, through the same
> realization authority the implementor and validator already use, instead
> of from a `[B, 256, T]` literal.

When no contract is supplied the gate builds exactly the tensor it builds
today. That is not a hedge: it is the Regime-A property every Step-02/03/04
seam has kept, and it is what makes the change provable by byte-equality
rather than by argument.

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
| `256` in probe targets | `evaluate_vram_skill/wrapper.py:248` (the literal), `:196-205`, `:236` (prose); `batch_resolver.py:85` (prose) | **TASK-SHAPED TERM** — the contract's class axis | **DERIVE** via the parameterized `realize_shape` (§0.2) |
| `PSD_SEGMENT_LENGTH // seg_size` | `workload_resolvers.py:50`; `inference_skill/estimator.py:210`; `evaluate_time_skill/wrapper.py:92,357,767` | **TASK-SHAPED TERM** | already DERIVE — **tighten** ambient→injected |
| `_INFERENCE_VS_TRAINING_RATIO = 2.7` | `inference_skill/estimator.py:79` | **CALIBRATION** — empirical median, measurement table at `:69-74` | **KEEP CALIBRATION**, value unchanged |
| `_MAX_BATCH_TIMESTEPS = 800_000` | `evaluate_vram_skill/compute_intensity.py:40` | **CALIBRATION/RUNTIME cap** | **KEEP**, unchanged |
| batch candidate table (64…1) | `evaluate_vram_skill` | **CALIBRATION** | **KEEP**, unchanged |
| RSS caps 40/60/24 GiB, overheads | `core/sandbox_executor.py:121` (`_ROLE_DEFAULT_RSS_GB`) etc. | **RUNTIME limits** | **KEEP** — and note CLAUDE.md pins the 60 GiB inference cap |
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
preference, and it is **decided at C7** (§16) with the evidence recorded.
Gate **launch choreography** — exact timing, exact bounded command, and cost
projection within the normal autonomous validation budget — belongs to the
Implementation Working Rules and current Gate policy, **not** to this design
and **not** to the operator's design review.

**Binding for this PR: a real-training Gate is never launched autonomously.**
If C7 resolves the condition to REQUIRED, the Gate is listed as its own
item — separate from the deterministic validation of every other commit —
with its bounded command, expected wall time and cost projection written down
**before** it runs, and it waits for explicit operator approval. No commit
above depends on a Gate result to be considered complete; C0-C6 and C8 are
fully deterministic.

## 12. Validation budget

Mapped onto the commit plan (§16):

```text
C0  probe-shape capture + live/dead census
C1  parameterized realizer          -> byte-equality proof
C2  contract-accepting probe        -> no-contract equality proof
C3  transport                       -> arrival proof + drop mutation
C4  live wiring                     -> TIDMAD forecast/admission parity
C5  ambient -> injected profile     -> step-count + visited-sequence parity
C6  calibration pins + §3 audit     -> pin mutations
C7  Stage-B rung + Checkpoint C     -> family mutations + Gate-2 decision
C8  terminal regression + CI
```

**No local full suite. No real LLM.** Gate 2 only if §11's condition resolves
to REQUIRED at C7, bounded, and **never launched without operator
approval**.

## 13. Rollback boundary

Widened in revision 2 by OD-05b-1 — the probe half touches a Step-04a module
and the pre-flight IPC path:

| Surface | Commits |
|---|---|
| `agent/skills/model_io_probe_skill.py` (**additive only**) | C1 |
| `agent/skills/evaluate_vram_skill/` (`wrapper.py`, `isolated_probe.py`, `preflight_worker_main.py`, `preflight_adapter.py`) | C2, C3 |
| the tuner's VRAM pre-flight call site | C4 |
| `agent/skills/evaluate_time_skill/`, `agent/skills/inference_skill/estimator.py`, `agent/skills/training_skill/estimator.py`, `execute_tools/workload_resolvers.py`, `execute_tools/inference_single.py` | C5 |
| directly affected tests + node/skill docs | C0, C6-C8 |

Reverting C1-C4 restores the `[B, 256, T]` literal and the unparameterized
realizer; reverting C5 restores the ambient fallbacks. Nothing else.

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
- Deriving a term changes a TIDMAD forecast by even one unit → STOP; that is
  failure class 3, not a tolerance.
- The work requires touching `core/runtime_control` measurement identity →
  STOP (Step 07).
- A calibration record store is required to migrate a constant → STOP; the
  roadmap defers calibration records, and this PR has no such consumer.

Added in revision 2, from the C1-C5 audit:

- **A declared contract and `get_output_type(model_type)` disagree about the
  output semantic** (C2 §6) → STOP. Which of the two owns the answer is a
  real authority question, and silently preferring either would make the
  probe describe a different model than the one being admitted.
- **`realize_shape` would need per-axis extents** rather than one `symbolic`
  value (C1 §6) → STOP. That is a shape language, not a parameterization, and
  it belongs to whoever owns the contract schema.
- **A live profile consumer cannot be reached without changing a public
  signature 05b does not own** (C5 §6) → STOP.
- **`load_task_config()` would become newly fatal on a pre-flight path that
  never read it** (C4 §6) → STOP and reconsider the acquisition point.

## 16. Commit plan — per-commit checklists

**Semantic sequence is frozen on approval; exact Git commit count is NOT.**
Also not frozen: helper structure, source line numbers, test-file
decomposition, exact mutation implementation. Implementation may merge or
split engineering commits provided the semantic sequence, the §17
Definition of Done, the Stage-B rung, the Checkpoint-C property and the Gate
disposition are unchanged.

Line references are **reading aids captured at `82a548f8`**, not contracts.
Re-read the touched source immediately before each commit.

`[ ]` = not done · `[x]` = done **and** verified with recorded evidence.

**Dependency chain.** `C0 → C1 → C2 → C3 → C4` is the probe seam, built
inert-first: C1 and C2 change no production behaviour (no caller supplies a
contract yet), C3 adds transport, and **C4 is the first commit where a real
run behaves differently** — and only under a task that declares `model_io`.
`C5` (profile tightening) is independent of C1-C4 and may land in either
order. `C6`-`C8` close.

---

### C0 — pre-edit baselines and the live/dead estimator census

**1. Goal.** Capture the compatibility surfaces that no existing oracle
covers, *before* any production edit, and settle by inspection which
estimators are production-live — because §4's binding rule forbids
genericizing a dead one, and that decision changes what C2-C5 are allowed to
touch. Separate commit because a baseline captured after an edit proves
nothing about that edit.

**2. Scope.**
- New tests under `tests/unit/agent/evaluate_vram_skill/` (or the existing
  VRAM test module — settle by inspection, do not invent a path).
- A written census recorded in §17 of this document.
- **Non-goals**: no production file changes at all; no new fixtures for facts
  Step 02/03/04a already pin; no forecast-parity oracle that already exists.
- Depends on: nothing.

**3. Implementation plan.**
- [ ] Re-read `_build_probe_tensors` (`wrapper.py:176-249`) in full and
      record which inputs can move the built shape today (`loss_type`,
      `loss_name`, `model_type` → `get_output_type`).
- [ ] Capture the probe tensor **shape and dtype** actually built under
      TIDMAD for each reachable branch: `classifier` (long target),
      `regressor` (`[B, T]` float), `hybrid`/legacy (`[B, 256, T]` float).
- [ ] Classify **each** estimator on the resource path as
      `production live | diagnostic only | test-only | dead | fallback`,
      citing the caller that makes it live (or the absence of one).
- [ ] Record the census in §17, including which estimators C2-C5 may touch.
- [ ] Confirm by inspection which §6 oracles already exist (forecast
      breakdowns, admission identities, resolved batch size) and do **not**
      restate them.
- [ ] Confirm no capture restates a Step-02/03/04a baseline.

**Explicitly NOT required**: baselining every branch of the VRAM wrapper
merely because it exists. A branch whose shape cannot move when a contract is
supplied is not evidence for this PR.

**4. Validation plan.**
- *Unit*: the new probe-shape baselines pass on unmodified production code.
- *Integration/pseudo*: none required at C0.
- *Negative*: include the `UnknownOutputContractError` → `ValueError` path
  (`wrapper.py:230-240`); a baseline of the happy path alone cannot detect a
  migration that silently stops raising.
- *Backward-compat*: this commit **is** the parity instrument.
- *Gate*: **none**.

**5. Acceptance criteria.**
- [ ] Baselines pass against production code that is **byte-unchanged**
      (`git status --porcelain` lists no production file in this commit).
- [ ] The captured shapes are written as **hardcoded literals**, never
      re-derived from the code under test.
- [ ] Every reachable target-shape branch has exactly one case.
- [ ] The estimator census names, for each live estimator, the production
      caller that makes it live — a file:line, not a claim.
- [ ] Every estimator classified `dead`/`diagnostic` is listed in §17 as
      **out of scope for C2-C5**.

**6. Failure and edge cases.**
- An estimator's liveness cannot be settled from source → record it as
  `UNKNOWN` and treat it as out of scope; do not guess it live.
- A probe branch cannot be reached without a GPU → record the reachability
  route found; if it genuinely requires hardware, it belongs to Checkpoint C
  / the §11 Gate question, and this document is updated to say so.

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/agent/evaluate_vram_skill -q`
      *(confirm the real path at implementation time)*
- [ ] Record: test count, wall time, and explicit confirmation that zero
      production files were modified.

**8. Commit boundary.** Tests and a written census only. Independently
reviewable as "what we promise not to change, and what we are allowed to
touch". No production edit.

---

### C1 — additive parameterization of the 04a realizer

**1. Goal.** Give `realize_shape` caller-supplied extents so ONE realization
authority can serve both validation probes and capacity probes (§0.2 option
A). Separate commit because it modifies a **Step-04a-owned module** and must
be provably behaviour-preserving on its own, before any new consumer exists
to confuse the evidence.

**2. Scope.**
- `agent/skills/model_io_probe_skill.py` — `realize_shape` signature and body
  (`:109-140`); docstring; `__all__` untouched.
- **Non-goals**: no change to `PROBE_BATCH` (`:68`), `PROBE_SYMBOLIC_EXTENT`
  (`:75`), `LOSS_PROBE_BATCH` (`:293`), `LOSS_PROBE_LENGTH` (`:294`) or
  `_LEGACY_LOSS_PROBE_CLASSES` (`:372`); no change to `build_model_input`,
  `build_loss_probe_pair`, `declared_output_tensor`, `expected_output_shape`
  or `input_index_extent` **behaviour**; no new consumer.
- Depends on: C0.

**3. Implementation plan.**
- [ ] Re-read `realize_shape` and the `fixed → batch → symbolic` precedence
      it documents.
- [ ] Add keyword-only `batch: int | None = None` and
      `symbolic: int | None = None`, defaulting to the existing constants.
- [ ] Preserve the precedence exactly: a `fixed` extent is a DECLARED fact
      and must still win over both new parameters.
- [ ] Update the docstring to state that omitting both arguments is
      byte-identical, and why a `fixed` axis ignores them.
- [ ] Confirm no existing call site is edited in this commit.

**4. Validation plan.**
- *Unit*: for the shipped TIDMAD contract, `realize_shape(t)` returns the
  documented `(1, 256, 64)` output / `(1, 64)` input, unchanged.
- *Unit*: `realize_shape(t, batch=B, symbolic=T)` returns `(B, 256, T)` — the
  `fixed` class axis unmoved.
- *Negative*: a `fixed` axis is **not** overridden by `symbolic=`; a
  non-positive `batch`/`symbolic` is rejected or documented as unchecked —
  decide from the module's existing idiom, do not invent a new error class.
- *Backward-compat*: `build_model_input`, `expected_output_shape` and both
  node consumers produce byte-identical shapes.
- *Gate*: **none**.

**5. Acceptance criteria.**
- [ ] With both arguments omitted, `realize_shape` returns a tuple **equal**
      to the pre-change return for every contract in the existing 04a test
      fixtures — asserted by equality, not by inspection.
- [ ] With `batch=B, symbolic=T` supplied, a declared `fixed` class extent is
      still `256` in the returned tuple, and rank and axis order are those of
      the contract, not of any assumption in this module.
- [ ] The four probe constants are unchanged, asserted by value.
- [ ] Zero production call sites changed by this commit.
- [ ] A mutation that makes the new parameter override a `fixed` axis is
      **RED**.

**6. Failure and edge cases.**
- A contract with a batch-role axis that is *also* `fixed` → `fixed` wins;
  pin that precedence, since it is the one case where the two rules meet.
- A contract with more than one symbolic axis → **both** receive `symbolic`;
  record whether that is correct for the capacity probe, and if it is not,
  STOP rather than adding per-axis parameters (that would be a new shape
  language, not a parameterization).
- A caller passing `symbolic=` for a rank-2 input contract → must still be
  the input's own rank; nothing here may assume 3-D.

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/agent/skills -k model_io_probe -q`
      *(confirm the real path at implementation time)*
- [ ] Record counts, wall time, and confirmation that no existing 04a test
      required editing.

**8. Commit boundary.** One additive, defaulted signature change with zero
behaviour change, independently revertible. No consumer wiring bundled in.

---

### C2 — the VRAM probe accepts a contract (in-process, inert in production)

**1. Goal.** Let `_build_probe_tensors` derive its target from a supplied
contract, while every production caller still supplies none — so the seam is
reviewable before it is live. Separate from C3/C4 because "the helper can do
it" and "production does it" are different claims with different failure
modes, and Step 02b's precedent is explicit that a parameter with a `None`
default is invisible to every caller that never passes it.

**2. Scope.**
- `agent/skills/evaluate_vram_skill/wrapper.py` — `_build_probe_tensors`
  (`:176-249`) gains `model_io_contract: ModelIOContract | None = None`;
  `run_skill` (`:483`) accepts and forwards the same optional kwarg; the
  call site at `:588`.
- **Non-goals**: no caller supplies a contract yet; no transport; no change
  to dtype resolution (`get_target_torch_dtype`, `:214`), to the
  `UnknownOutputContractError` refusal (`:230-240`), or to any calibration.
- Depends on: C1.

**3. Implementation plan.**
- [ ] Re-read `_build_probe_tensors` and `run_skill`'s kwargs contract
      (`:483-520`) — note it is `**kwargs`, so the addition is additive.
- [ ] Add the optional parameter and thread it from `run_skill` to the
      `:588` call site.
- [ ] With a contract: derive the target shape via `declared_output_tensor`
      + the C1-parameterized `realize_shape(..., batch=batch_size,
      symbolic=seg_size)`.
- [ ] Without a contract: take exactly today's path, including the
      `get_output_type` branch and the `[B, 256, T]` literal.
- [ ] Decide and record where **dtype** comes from when a contract is
      supplied — the loss (today's rule) remains the dtype authority; the
      contract supplies shape only. Do not silently move dtype ownership.
- [ ] Update `evaluate_vram_skill.md` for the new optional kwarg.

**4. Validation plan.**
- *Unit*: contract supplied → the built target equals `(B, 256, T)` for the
  TIDMAD contract at real `B`/`T`; contract omitted → byte-identical to the
  C0 baseline.
- *Unit*: a contrast contract with a different class extent moves the target
  shape and **nothing else** (dtype, input shape unchanged).
- *Negative*: the `UnknownOutputContractError` → `ValueError` path still
  raises when no contract is supplied; a malformed contract fails loudly
  rather than falling back to `[B, 256, T]` — **a silent fallback here is
  the defect this commit must not introduce**.
- *Backward-compat*: every C0 baseline passes unchanged.
- *Gate*: **none**.

**5. Acceptance criteria.**
- [ ] With `model_io_contract=None`, the returned `(input, target)` shapes
      and dtypes are **equal** to the C0 baseline for every branch.
- [ ] With the shipped TIDMAD contract supplied, the target shape equals the
      no-contract shape **exactly** — this is the whole Regime-A claim, and
      it is an equality assertion, not a narrative.
- [ ] With a contrast contract, the class axis moves and `batch_size` /
      `seg_size` are honoured at their real values (not `1` / `64`).
- [ ] Target **dtype** still comes from the loss in both paths.
- [ ] No production caller passes a contract yet — asserted by inspection and
      recorded, so C4's evidence cannot be confused with C2's.

**6. Failure and edge cases.**
- Contract declares a `regressor` output → target is `[B, T]`; must agree
  with today's `get_output_type` branch under TIDMAD.
- Contract and `model_type` disagree about the output semantic → **STOP**
  and record; do not silently prefer one. That is a genuine authority
  question, not an implementation detail.
- Contract present but unrealizable (`ProbeConstructionError`) → propagate as
  the module's existing `ValueError` idiom; never fall back to the literal.

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/agent/evaluate_vram_skill -q`
- [ ] Record counts, wall time, and the no-contract equality result.

**8. Commit boundary.** One helper and one entry point, inert in production,
independently revertible. No transport, no tuner change.

---

### C3 — contract transport across the pre-flight worker boundary

**1. Goal.** Carry an optional contract from the parent to the isolated
pre-flight child, so the live production path (which is a subprocess) can use
what C2 added. Separate commit because it is IPC-shaped work with its own
failure mode — a field that serializes but never arrives — and because it is
still inert until C4 supplies a contract.

**2. Scope.**
- `agent/skills/evaluate_vram_skill/isolated_probe.py` — `IsolatedProbeSpec`
  (`:168-182`) gains one optional field beside `model_config_payload` /
  `train_config` / `loss_config`.
- `agent/skills/evaluate_vram_skill/preflight_worker_main.py` — rebuild and
  forward it into `run_skill` (`:190-205`).
- `agent/skills/evaluate_vram_skill/preflight_adapter.py` —
  `run_production_preflight` (`:212-223`) gains the matching optional
  parameter.
- **Non-goals**: no change to `HardwareSnapshot`'s six-attribute surface
  (a seventh read is pinned by an existing test); no change to
  `effective_cap_gb`, deadlines, or worker memory limits.
- Depends on: C2.

**3. Implementation plan.**
- [ ] Re-read `IsolatedProbeSpec` and the worker's `spec.get(...)` rebuild.
- [ ] Follow the established pattern: `train_engine_sandbox.py:1249`
      (`--model_io_json`) + `load_model_io_contract`
      (`model_io_contract.py:312`) — decide between an inline JSON field on
      the spec and a path, and record why. The spec is already a transient
      JSON IPC file, so an inline dump is the lower-ceremony option.
- [ ] Thread parent → spec → worker → `run_skill`.
- [ ] Confirm `None` remains legal end to end and produces today's behaviour.

**4. Validation plan.**
- *Unit*: a spec round-trips through JSON with the contract intact and
  revalidates to an **equal** `ModelIOContract`.
- *Integration/pseudo*: the worker path forwards the contract into
  `run_skill` — asserted at the `run_skill` boundary, not by reading the spec
  file back.
- *Negative*: absent field → `None` → today's behaviour; malformed contract
  in the spec → fails loudly in the child with a diagnostic naming the field,
  never a silent `None`.
- *Backward-compat*: an old spec JSON with no such field still loads.
- *Gate*: **none**.

**5. Acceptance criteria.**
- [ ] A contract placed on the spec **arrives at `run_skill`** in the child —
      proven by a test that fails if the forwarding line is deleted, not by a
      grep for the field name.
- [ ] Spec JSON without the field validates and behaves exactly as today.
- [ ] `HardwareSnapshot`'s attribute surface is unchanged (the existing
      six-attribute test still passes untouched).
- [ ] A transport mutation — drop the field in the worker rebuild — is
      **RED**.

**6. Failure and edge cases.**
- Contract too large / non-JSON-native after dump → must fail at the parent
  with a clear diagnostic, not produce a truncated child spec.
- Worker launched by older tooling with a stale spec → absent field is legal
  and means Regime A.
- Propagation failure (child cannot rebuild the contract) → **fail the
  pre-flight loudly**; do not fall back to the literal shape, because a
  silently-wrong probe reports a capacity number for a different model.

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/agent/evaluate_vram_skill -q`
- [ ] Record counts, wall time, and the transport-mutation result.

**8. Commit boundary.** IPC only. No behaviour change while no caller
supplies a contract. No tuner change.

---

### C4 — the tuner supplies the contract (first live consumer)

**1. Goal.** Make the live resource gate the third production consumer of the
probe authority. **This is the first commit that can change a real run's
behaviour**, and only for a task that declares `model_io` — which is why it
is isolated.

**2. Scope.**
- The tuner's pre-flight call path — `_run_time_preflight`'s VRAM sibling and
  `run_production_preflight`'s caller in
  `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py`
  (`run_production_preflight` imported at `:54`).
- Contract acquisition: `workflows/task_config.load_task_config()` →
  `ForwardContract(**cfg["forward_contract"]).model_io` — the resolved
  production entry point (`workflows/task_config.py:172`), which is `None`
  for a legacy prose-only task.
- **Non-goals**: no new field on `HyperparamTuningInput`; no new CLI
  argument; no change to admission thresholds, retry or refusal semantics;
  no ambient contract lookup inside the skill.
- Depends on: C3.

**3. Implementation plan.**
- [ ] Re-read the tuner's VRAM pre-flight call site and confirm the exact
      acquisition point (tuner vs. adapter) from the call chain — **do not
      assume**; record the choice and why.
- [ ] Obtain the contract through the canonical accessor, once per run, at a
      point that adds **no branch** to `run()` (CLAUDE.md: `run()` sits on
      pyright's strict complexity ceiling).
- [ ] Pass it through `run_production_preflight`.
- [ ] Confirm a task with no `model_io` yields `None` and today's behaviour.
- [ ] Update the tuner node doc and `evaluate_vram_skill.md`.

**4. Validation plan.**
- *Unit*: with a `model_io`-declaring task config, the contract reaches
  `run_skill`; with a legacy config, `None` does.
- *Integration/pseudo*: a real tuner pre-flight path — not a helper — carries
  the contract end to end.
- *Negative*: a task config whose `model_io` fails resolution must fail at
  the existing `resolve_model_io_contract` boundary, before any probe runs;
  05b must not add a second resolution point.
- *Backward-compat*: under TIDMAD the **resolved batch size, the forecast
  breakdown and the admission/refusal decision are identical** to C0.
- *Gate*: see §11 — the condition is decided at C7, not here.

**5. Acceptance criteria.**
- [ ] Under TIDMAD, admission decision, resolved batch size and forecast
      breakdown are **equal** to the C0 baseline — a single unit of drift in
      any breakdown term is failure class 3 and a **STOP**, not a tolerance.
- [ ] A legacy prose-only task config still runs the gate with `None`.
- [ ] The contract is acquired **once per run**, and no 05b consumer performs
      its own ambient contract lookup — asserted semantically, not by a call
      count.
- [ ] `run()` gains no new branch (verified by reading the diff, since the
      complexity ceiling is not observable from tests).
- [ ] No new schema field, CLI argument or persisted configuration.

**6. Failure and edge cases.**
- `load_task_config()` raises for an unrelated reason at pre-flight time →
  must not be newly fatal on a path that previously did not read task config;
  if it would be, **STOP** and reconsider the acquisition point.
- Contract present but the candidate is a plugin whose declared output
  disagrees → the C2 stop condition applies.
- Resume of a run started before this commit → nothing persisted changes, so
  resume is unaffected; assert it rather than assume it.

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent tests/unit/agent/evaluate_vram_skill -q`
- [ ] Record counts, wall time, and the TIDMAD equality results.

**8. Commit boundary.** Production wiring only. No probe-logic change, no
transport change, no unrelated cleanup.

---

### C5 — ambient → injected `DatasetProfile` on the live resource path

**1. Goal.** Remove the `profile or resolve_dataset_profile()` fallback shape
from the live resource path, so a run bound to a contrast topology cannot be
**priced** against the ambient one. Independent of C1-C4; grouped separately
because it is the Step-02b defect shape, not a Model-I/O concern.

**2. Scope.**
- `execute_tools/workload_resolvers.py` — `_validate_seg` (`:49`) and
  `resolve_inference_workload` (`:139`).
- `agent/skills/inference_skill/estimator.py:208`.
- `agent/skills/evaluate_time_skill/wrapper.py:92, :357, :767`.
- The four production callers that must now supply a profile:
  `evaluate_time_skill/wrapper.py:515`,
  `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:2914`,
  `agent/skills/training_skill/estimator.py:493`,
  `execute_tools/inference_single.py:563`.
- **Non-goals**: no change to strategies, portions, seeds, **ordering**, or
  `SampleSet` shape/serialization; no new CLI argument; `core/runtime_control`
  untouched (Step 07).
- Depends on: C0 (the estimator census says which of these are live).

**3. Implementation plan.**
- [ ] Re-read each of the four call sites and record whether a resolved
      profile is already in scope.
- [ ] `inference_single.py` **already loads one** (`:336-339`,
      `dataset_profile` / `profile_dataset`) and simply does not pass it to
      `resolve_inference_workload` at `:563` — thread it; this is a
      one-argument fix and the clearest instance of the defect.
- [ ] For each remaining caller, thread the run-bound profile; where none is
      in scope, record the acquisition point rather than inventing one.
- [ ] Decide per function whether the parameter becomes **required** or stays
      optional-with-fallback, and record the reason. Required is preferred
      where every production caller can supply it (the 05a precedent); a
      fallback that no production caller relies on is dead permission.
- [ ] Leave `evaluate_time_skill/wrapper.py`'s reads consistent with whatever
      the enclosing function receives — do not create a second acquisition.

**4. Validation plan.**
- *Unit*: under a bound contrast profile, each migrated resolver returns the
  contrast-derived step/batch counts, not the TIDMAD ones.
- *Integration/pseudo*: a real pre-flight/time path prices against the bound
  profile.
- *Negative*: a caller that supplies no profile either fails loudly (if the
  parameter became required) or is proven to be a non-production caller.
- *Backward-compat / default-parity*: **under TIDMAD every step count,
  batch count and `output_bytes` value is identical to C0.**
- *Gate*: **none**.

**5. Acceptance criteria.**
- [ ] Under TIDMAD, `resolve_training_workload`, `resolve_inference_workload`
      and `resolve_scoring_workload` return values **equal** to the C0
      baseline — field by field, including `detail["output_bytes"]`.
- [ ] **Default-path invariance, asserted on the sequence and not on the
      config**: for the default (`shuffle`) ordering path, the *visited
      file/sample sequence*, the resolved seeds and the **total step count**
      are unchanged. 05b touches the step-count producer, so proving the
      configuration value unchanged would be proving the wrong thing.
- [ ] Under a contrast profile, the derived step counts move and no
      calibration constant does.
- [ ] An ambient-regression mutation (restore `profile or
      resolve_dataset_profile()` at a migrated site) is **RED**.
- [ ] `grep "profile or resolve_dataset_profile()"` over the live resource
      path returns zero — recorded as **supporting evidence only**; the
      semantic guard above is the property.

**6. Failure and edge cases.**
- **Scope mismatch**: a profile bound at the parent but absent in a
  subprocess → the subprocess must load its own explicitly
  (`inference_single.py:336-339` is the pattern) and **fail closed** when a
  path is supplied but unreadable — `load_dataset_profile` already does this;
  do not weaken it.
- **Legacy configuration**: a caller predating the transport must keep
  working *or* be proven non-production. Record which.
- **Resume**: step counts are recomputed, not persisted, so a resumed run
  must produce identical counts under TIDMAD — assert it.
- **Propagation failure**: if a profile cannot be threaded to a live site
  without changing a public signature that 05b does not own → **STOP**.

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/execute_tools tests/unit/agent/tune_ml_hyperparam_agent -q`
- [ ] Record counts, wall time, the TIDMAD equality results, and the
      ambient-mutation result.

**8. Commit boundary.** One defect family across its live call sites,
independently revertible. No Model-I/O work, no calibration change.

---

### C6 — calibration pins and the §3 seg-fallback audit record

**1. Goal.** Make "calibration was not migrated" a *checked* property rather
than a promise, and discharge the §14 ledger's audit obligation. Separate
commit because it is the anti-scope evidence: it exists to fail if a later
edit reclassifies an empirical constant as task configuration.

**2. Scope.**
- New pins in the relevant existing test modules.
- §3 of this document + the §14 roadmap row (docs).
- **Non-goals**: no production change of any kind; no constant is moved,
  renamed or re-owned.
- Depends on: C5.

**3. Implementation plan.**
- [ ] Pin `_INFERENCE_VS_TRAINING_RATIO == 2.7`
      (`inference_skill/estimator.py:79`).
- [ ] Pin `_MAX_BATCH_TIMESTEPS == 800_000` (`compute_intensity.py:40`).
- [ ] Pin `SEG_SIZE_BOUNDS == (2500, 40_000)` (`trigger_policy.py:34`).
- [ ] Pin `_ROLE_DEFAULT_RSS_GB` incl. the **60 GiB inference cap** CLAUDE.md
      names as a subsystem invariant (`core/sandbox_executor.py:121`).
- [ ] Pin the batch candidate table.
- [ ] Record the three `core/runtime_control` seg fallbacks
      (`gpu_measurement_identity.py:214`,
      `gpu_measurement_worker_main.py:254`, `probe_production.py:220`) as
      **Step-07 owned, not fixed here**.
- [ ] Update the §14 row to record *no single semantic behind "40000"* and
      retire its speculative "`§7d` resolver" owner.

**4. Validation plan.**
- *Unit*: each pin asserts a **hardcoded** expected value.
- *Negative*: none — a pin's negative case is the mutation below.
- *Backward-compat*: n/a (no behaviour change).
- *Gate*: **none**.

**5. Acceptance criteria.**
- [ ] Every pin compares against a literal written in the test, never against
      the module attribute it guards (that would compare the code to itself).
- [ ] Changing any pinned constant makes exactly the intended pin **RED**.
- [ ] The §14 row no longer names a `§7d` resolver.
- [ ] Zero production files modified by this commit.

**6. Failure and edge cases.**
- A pinned constant is already asserted elsewhere → **do not duplicate**;
  cite the existing pin instead. Test economy is binding (CLAUDE.md).
- A constant turns out to have a live *derivation* rather than a literal →
  record it; pinning a derived value would freeze the derivation by accident.

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/agent/skills tests/unit/core -k "calibration or intensity or trigger" -q`
      *(confirm selectors at implementation time)*
- [ ] Record counts, wall time, and each pin's mutation result.

**8. Commit boundary.** Evidence and documentation only.

---

### C7 — Stage-B rung, Checkpoint C, and the Gate-2 decision

**1. Goal.** Prove the capability holds, cannot silently regress, and settle
§11's Gate-2 condition **from evidence**. Separate from C1-C5 so a reviewer
reads the behaviour change and the "what must never regress" decision
independently.

**2. Scope.**
- New/extended tests: the Stage-B contrast rung, the Checkpoint-C scenario,
  and the family mutations.
- §11 and §17 of this document.
- **Non-goals**: no production behaviour change in this commit.
- Depends on: C4, C5, C6.

**3. Implementation plan.**
- [ ] Build the **single-axis** Stage-B contrast (§8): a contract whose class
      extent differs from 256, with topology, calibration, hardware and
      policy held fixed.
- [ ] Prove the derived probe shape and the dependent forecast term move,
      while `2.7`, the intensity cap, the batch table and the hardware
      context stay byte-identical.
- [ ] Build the Checkpoint-C scenario: the **real** production VRAM/time gate
      prices and admits a real attempt using derived terms.
- [ ] Run the family mutations and record each observed result:
      probe-shape ambient regression; profile ambient regression;
      calibration-drift; contract-transport drop.
- [ ] **Decide the Gate-2 condition** (§11) and record the evidence:
      deterministic production-path evidence fully exercises the live
      admission decision → NOT REQUIRED; otherwise REQUIRED.

**4. Validation plan.**
- *Unit*: the contrast rung and the mutations.
- *Integration*: Checkpoint C through the real gate, not a helper.
- *Negative*: the guard must **not** fire on the legitimate single
  contract/profile binding.
- *Backward-compat*: TIDMAD parity unchanged by this commit (it adds no
  production change).
- *Gate*: **Gate 2 only if §11's condition resolves to REQUIRED — and it is
  listed here separately and must NOT be launched without operator
  approval.** Gate 1 remains NOT REQUIRED unless a resource literal reaches a
  prompt.

**5. Acceptance criteria.**
- [ ] Reintroducing ambient behaviour reds for **each** family — probe shape,
      profile, transport — with each mutation's site count asserted as
      exactly 1 before it is applied.
- [ ] Every mutation is restored from clean source and the tree re-verified
      green.
- [ ] Checkpoint C crosses the real production gate; a helper-only
      substitution is explicitly rejected in the record.
- [ ] The Gate-2 branch is recorded with the **source evidence** that settled
      it, not a preference.
- [ ] No production file is modified by this commit.

**6. Failure and edge cases.**
- A mutation **survives** → inspect the test architecture before adding an
  assertion; classify (real gap / equivalent / unreachable / wrong fixture).
- The live probe cannot run without a GPU → that is the §11 Gate-2 trigger,
  **not** a licence to weaken Checkpoint C into a helper test.
- The contrast contract moves a calibration value → the contrast is wrong;
  rebuild it single-axis.

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/agent/evaluate_vram_skill tests/unit/agent/tune_ml_hyperparam_agent tests/unit/execute_tools -q`
- [ ] Record counts, wall time, each mutation's expected vs observed result,
      the restored-green re-run, and the Gate-2 decision with its evidence.

**8. Commit boundary.** Evidence only. No production change.

---

### C8 — terminal regression, docs, CI

**1. Goal.** Establish terminal evidence and leave the PR reviewable.

**2. Scope.** §17 ledger, the touched node/skill `.md` files, CI iteration.
**Non-goals**: no new capability; no scope expansion.
Depends on: C7.

**3. Implementation plan.**
- [ ] Synchronize §17 with actual findings, deviations and evidence.
- [ ] Update `evaluate_vram_skill.md` and the tuner node doc as the **last**
      pre-merge step, quoting each documented kwarg/default against merged
      source (CLAUDE.md doc-sync rule).
- [ ] Run the terminal checks from a **clean tree**.
- [ ] Open/update the PR; drive exact-final-head CI green.
- [ ] Verify local HEAD == PR `headRefOid` == successful CI `headSha`.

**4. Validation plan.**
- Directly affected tests · focused integration · mutations · `ruff check` ·
  `ruff format --check` · required static/type checks · exact-head CI.
  **No local full suite by default.** Gate only if C7 decided REQUIRED.

**5. Acceptance criteria.**
- [ ] Every verdict read from the **log file**, never a wrapper's exit
      status.
- [ ] The three identities match, each read rather than reconstructed.
- [ ] Working tree clean; §17 records every deviation.
- [ ] If local pyright cannot run (the 05a precedent: host Node too old),
      that limitation is **recorded** and no local type claim is made.

**6. Failure and edge cases.**
- Full-suite/preflight guard reds on a dirty tree → commit the checkpoint
  first; never relax the guard.
- CI fails on an environment-only check → diagnose and fix autonomously; not
  a stop condition.

**7. Verification commands and evidence.**
- [ ] The terminal command set, with counts and wall time recorded.
- [ ] CI run id and exact `headSha`.

**8. Commit boundary.** Documentation and CI-driven fixes only.

---

### 16.1 Commit-boundary discipline (binding for every commit above)

Before each commit, **stop and show**: the exact `git diff --stat`, the staged
file list, the tests run with counts and wall time, and any deviation from
this plan. A commit that cannot be described that way is not ready.

Never mark a checklist item `[x]` before the evidence exists. An unperformed
exact command is recorded as **DEVIATED** or **SUPERSEDED** with what was
actually run — the 05a precedent (its §18 reconciliation).

## 17. Definition of Done — the authoritative checkpoint table

**This table governs.** Where any lower-level checklist in §16 diverges from
it, this table wins.

### CHECKPOINT 0 — pre-edit baselines
- [ ] probe tensor shape/dtype baseline captured for every reachable branch
- [ ] live/dead estimator census recorded, each live one naming its caller
- [ ] captured **BEFORE** any production edit
- [ ] no duplication of existing Step-02/03/04a baselines

### CHECKPOINT A — TIDMAD / replay parity
- [ ] forecast breakdowns **deep-equal** (train/inference/scoring)
- [ ] admission/refusal decisions and identities identical
- [ ] resolved batch size per candidate identical
- [ ] probe tensor shapes/dtypes identical with no contract supplied
- [ ] calibration constants unchanged, asserted by pin
- [ ] step counts and the default-path visited sequence unchanged
- [ ] model / loss / train / `TrialConfig` schemas unchanged; CLI unchanged
- [ ] a representative historical TIDMAD configuration loads **without
      migration** and resolves to the same effective semantics

### CHECKPOINT B — generic consumption
- [ ] single-axis contrast: class extent moves the derived probe shape
- [ ] calibration, hardware and policy provably fixed across that contrast
- [ ] family mutations red appropriately (probe shape · profile · transport ·
      calibration drift)
- [ ] no ambient profile fallback and no ambient contract lookup remains in a
      live resource consumer

### CHECKPOINT C — production path
- [ ] the real production VRAM/time gate prices and admits a real attempt
      using derived terms
- [ ] no helper-only substitution
- [ ] §11's Gate-2 condition decided from recorded source evidence

### CHECKPOINT D — regression / static
- [ ] directly affected deterministic tests
- [ ] focused integration
- [ ] mutations restored and re-verified green
- [ ] `ruff check` + `ruff format --check`
- [ ] required static/type checks (or a recorded environment limitation)
- [ ] exact-final-head CI green
- [ ] no local full suite by default

### GATES
- [ ] **Gate 1 NOT REQUIRED** — re-verified; flips only if a resource literal
      reaches a rendered prompt
- [ ] **Gate 2** — decided at C7 by §11's semantic condition. If REQUIRED, it
      is bounded, listed separately, and **launched only with operator
      approval**

### READY FOR OPERATOR REVIEW
- [ ] Checkpoints 0/A/B/C/D complete
- [ ] Gate disposition re-verified at the final head
- [ ] node/skill docs synchronized as the last pre-merge step
- [ ] PR opened/updated; exact-final-head CI green
- [ ] local HEAD == PR `headRefOid` == successful CI `headSha`
- [ ] working tree clean

## 18. Implementation ledger

*(empty — populated at implementation kickoff)*

## 19. Remaining operator decisions

**NONE outstanding.** Two were raised by the revision-2 audit and are now
decided:

| Decision | Resolution |
|---|---|
| **OD-05b-1** — how the resource gate consumes the probe authority, given that `realize_shape` realizes at validation extents and no contract reaches the gate | **Option A**: additively parameterize `realize_shape` and plumb an optional contract (§0.2). Options B and C recorded as rejected, with reasons |
| **OD-05b-2** — whether to re-anchor rev-1's `13b08550` citations | **Yes**: §0.3 is the corrected table; the original blocks are preserved as chronology |

Everything else is resolved from source: the classification table (§2) by the
constants' documented derivations, the seg-fallback disposition (§3) by the
sites' differing meanings, and the Gate disposition (§11) by a semantic
condition that implementation evidence settles at C7.

## 20. Configuration-architecture preservation (Step-05 cross-cutting invariant)

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
