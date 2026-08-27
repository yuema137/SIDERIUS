# FINAL CAMPAIGN REVIEW PACKAGE — official Gold campaign

**STATUS: DRAFT. §4 first, per the Supervisor's sequencing. Sections are
released for cross-check as they stabilise, not held for one final document.**

**The standard this package must meet:**

> The operator must understand exactly what will happen after pressing
> "launch", **without reconstructing the protocol from code, issue threads, the
> decision ledger, or historical agent transcripts.** It must describe the
> **ACTUAL EXECUTABLE campaign, not the intended design.**

**Division of labour (frozen, §14):** this lane assembles the
scientific/protocol description and checks it against the frozen Parts 1–8
authority; the Supervisor mechanically verifies that the description matches the
**actual released code, standalone package, hardware qualification and launch
behaviour.** **Neither side self-certifies its own assumptions where the claim
is load-bearing.** One coherent package, not two lane reports stapled together.

**This document is not a launch authorization.** A report that says READY does
not itself authorize launch; the operator's acceptance does.

---

## §1 WHAT THIS CAMPAIGN IS

### 1.1 The scientific question

**Does giving an autonomous research agent prior information about a problem
change the quality of the science it produces?**

Two arms run the same framework, on the same data, under the same frozen
resource and validity constraints. One receives prior information; the other
explicitly does not. Everything else is held fixed by construction.

| arm | pod | treatment |
|---|---|---|
| **Gold** | `goldpod` | `WITH_ADVICE` — at **every proposer round**: (A) an immutable general optimization-advice artifact, (B) an immutable prior-TIDMAD-baseline-information artifact |
| **Blind** | `blindpod` | `WITHOUT_ADVICE` — both components **explicitly** disabled |

**The comparison the design intends** (`D-TREAT`, plan §5.10, frozen):

```text
      same opportunity  +  different prior information

  and NOT

      different engineering capability
```

Any difference that arises because the two agents made different *legitimate*
`AGENT_CONTROLLED` scientific choices is a **campaign outcome, not a
configuration asymmetry**. That distinction is what the whole control plane
exists to protect.

### 1.2 Why Blind is not simply "the flag left off"

The frozen constraint (plan §5.6) forbids implementing Blind by omission:

> Do **not** implement this merely through omission. Do **not** rely on any
> framework default. The final frozen configuration **and effective argv** must
> **explicitly materialize the absence of both treatment components.**

**The reason is auditability, and it generalises well beyond this campaign.** An
absence produced by omission is indistinguishable from an absence produced by a
dropped flag, a launcher bug, or a future default change. Only an explicitly
recorded *"off"* can be audited after the fact. If Blind's advice is absent
because nobody passed the flag, then a year from now nobody can prove the arm
was actually blind — and the experiment's control arm becomes unfalsifiable.

**Two launch gates enforce this**, both required, neither sufficient alone:

- **§5.8 Gold positive witness** — advice provably *reached* the proposer;
- **§5.7 Blind negative witness** — no advice reached it by any route.

> **A negative audit alone cannot distinguish "the treatment was withheld" from
> "the treatment was never delivered to either arm."** That is why the positive
> witness is not optional bureaucracy: it is the only thing that proves the
> delivery mechanism worked at all. `T-IMPL-1` — the launcher currently refusing
> advice in **both** arms — is precisely the failure the positive witness exists
> to catch, and it was found by reading the launcher rather than by running it.

### 1.3 The task

TIDMAD / SQUID signal denoising. The agent proposes model architectures, tunes
them, trains them, and is scored by the **frozen Golden Metric**. The metric is
the task definition and is **never** modified to make a result look better.

**Scope: 20 data files, partitioned into 4 bands** — `0-3`, `4-9`, `10-14`,
`15-19` (a 4/6/5/5 split). Each band runs its own independent chain.

> ⚠️ **The band partition is a scheduling device, not a scientific
> aggregation.** `scoring_utils.py` §3 explicitly forbids "mean of per-band
> linear means (e.g. 4/6/5/5)" — and 4/6/5/5 is exactly this partition. A
> cross-band number is only valid as **ONE `score_vector` call over scope
> `0..19`**. This is recorded here, in the section that introduces bands,
> because the invalid construction is the *intuitive* one.

---

## §2 WHAT HAPPENS AFTER YOU PRESS LAUNCH

**This section describes the ACTUAL executable behaviour, not the intended
design.** Where the two differ, the difference is marked and carries a §6 row.

### 2.1 The call chain

```text
launch_band_fleet.sh                    4 bands: 0-3 · 4-9 · 10-14 · 15-19
  └── launch_prior_baseline_experiment.sh     <-- ⚠️ see §4.0a
        └── run_chain.sh
              └── _chain_common.sh            <-- where the values actually resolve
                    └── run_one_iteration.py
                          └── workflows/model_exploration.py::run_workflow
```

**Read §4.0a before reading any parameter value in this document.** The second
line of that chain is the one that decides whether the frozen values in §4 reach
the run at all. **They currently do not.**

### 2.2 One iteration

Each iteration of `run_workflow` is a full research cycle:

```text
literature/context  ->  PROPOSE  ->  IMPLEMENT  ->  VALIDATE code
                          |
                          v
                    TUNE (rounds)
                      trial round(s)   small data portion, cheap
                          |
                          v
                      formal round     larger portion, the scored one
                          |
                          v
                    train -> infer -> score -> HealthGates
                          |
                          v
                    REFLECT  ->  INTERPRET  ->  next iteration
```

**The treatment enters at exactly one point: PROPOSE.** Gold's two artifacts are
injected into the proposer's context at every proposer round; nothing else in
the loop differs between arms.

### 2.3 What the operator should expect to see

| | |
|---|---|
| **iterations per band** | **20** *(frozen `D-BUD-2`; the effective path currently passes 10 — §6.1 B)* |
| **bands** | 4, concurrent, independent chains |
| **rounds per iteration** | up to 3 tuner rounds |
| **who chooses the model** | the agent — this is the whole point |
| **who chooses data portions** | **frozen as `EXPERIMENT_FIXED`** — but see §6.1 B: on the effective path they are currently **agent-controlled by omission** |
| **wall-clock bound** | **none on the effective path** (§6.1 C) |

### 2.4 The honest summary of §2

**If launched today, the run would execute — and it would not be the campaign
described in §4.** It would run 10 iterations rather than 20, with
agent-chosen rather than frozen data portions, inverted formal sampling, no
wall-clock ceiling, no watchdog, lenient per-file health aggregation, and **no
advice reaching the Gold arm at all** — which would make the two arms identical
and the experiment empty.

That is not a reason for alarm; it is the reason this package exists. **Every
one of those is a §6 row with an owner.** But it is why "the code runs" must
never be mistaken for "the campaign is ready."

---

## §3 WHAT MUST BE DECIDED BEFORE LAUNCH

**Six decisions are open and belong to the operator.** None can be resolved by
either working lane; each is recorded with what is known so the decision is made
against evidence rather than a preference.

| id | question | why it cannot be delegated | consequence of leaving it open |
|---|---|---|---|
| **`F-LAUNCH-2`** | **No existing launcher implements this campaign's experiment. Which one will?** | It touches X9's reproducibility, so it is not a pure implementation choice | **The campaign cannot be run at all.** See §3.0 |
| **`F-LAUNCH-1`** | Which launcher supplies the twelve untyped values? | It determines *where* thirteen other repairs must land | **13 release blockers cannot be correctly routed.** Repairs aimed at the wrong launcher would pass review and change nothing. **Sub-case of `F-LAUNCH-2`** |
| **`Q-UNIT-1`** | Is the 60 VRAM ceiling **GB or GiB**? | A numeric resource ceiling is `EXPERIMENT_FIXED` | H100 qualification would measure against an undefined target. Recommendation: **GiB** — 60 GiB = 64.4 GB; an 80 GB card is 79.6 GiB; headroom 19.6 GiB |
| **`Q-LIT-1`** | Is literature review enabled for the formal campaign? | It changes the agent's information environment — i.e. it is treatment-adjacent | Unresolved, the arms' information symmetry is unproven |
| **`Q-ISO-1`** | `--baseline_isolation` disposition (I1/I2/I3/I4) | Determines what prior TIDMAD information the framework itself leaks | Blind's negative witness cannot be specified |
| **`F-LLM-2`** | Retry policy: frozen **indefinite** vs shipped **bounded at 3** | Coupled to whether an API failure consumes a scientific attempt | An infrastructure failure silently spends scientific budget (§6.1 F row 89) |

### 3.0 ⚠️ `F-LAUNCH-2` — the band-fleet stack implements a DIFFERENT experiment

This is the most serious finding in the package and it reframes `F-LAUNCH-1`
rather than adding to it.

```text
launch_band_fleet.sh:100-101       --card A -> ARM="with-prior-art"
                                   --card B -> ARM="without-prior-art"
                                   any other --arm value is REJECTED

launch_prior_baseline_experiment.sh:163-168
  with-prior-art     --ml_lit_review_enabled     --experiment_arm with-prior-art
  without-prior-art  --no-ml_lit_review_enabled  --experiment_arm without-prior-art
                     --baseline_isolation

:142-146   --advice / --human_advice_file REFUSED. Reason, verbatim:
           "the experiment's only variable is the literature-review topology"
:147-149   --ml_lit_review_enabled / --experiment_arm / --baseline_isolation
           refused as passthrough: "decided by --arm and cannot be passed through"
```

**There is no advice arm anywhere in the fleet path.** The stack implements
**X9**, whose independent variable is literature-review topology. **This
campaign's independent variable is advice.**

**Launched on this stack today, the campaign would run a confounded
three-variable experiment with its own treatment disabled:**

| | difference between arms | what it is |
|---|---|---|
| 1 | **advice REFUSED in both arms** | **the treatment is not delivered at all** |
| 2 | lit-review ON in A, explicitly OFF in B | a **second** treatment variable |
| 3 | `baseline_isolation` off in A, ON in B | a **third** treatment variable |
| 4 | `experiment_arm` stamps `with-prior-art` | **wrong provenance — and pinned** |

Differences 2 and 3 violate §5.10 directly: the design compares *same
opportunity + different prior information*, **not different engineering
capability**. Two of the three arm differences would be capability differences.

> **Item 4 is the one to flag hardest.** `experiment_arm` is in
> `RunInvariants._CANONICAL` (`core/run_invariants.py:253`), so a wrong arm
> label is **pinned and compared**, not merely recorded. **Wrong provenance that
> fails closed on resume is worse than absent provenance** — it looks
> authoritative, and it is self-consistent.

**One piece of good news, and it bounds the work.** The capability is not
missing; only the campaign path blocks it. `_chain_common.sh` already has full
advice support — parse `:322-323`, validation `:430-441`, forwarding
`:556-558`. **This is a launcher-layer problem, not a framework one.** The layer
that would have been expensive to fix is already correct.

**No fix is proposed here.** Whether the campaign gets its own launcher or the
fleet gains advice arms is a design decision with an operator dimension, because
it touches X9's reproducibility — and that launcher's own error text says X9
reproducibility is exactly what it is protecting. Two constraints any answer
must satisfy: **the campaign's arms must differ in advice ONLY**, and
**`experiment_arm` must stamp a label naming THIS experiment.**

### 3.1 The one that gates the others

**`F-LAUNCH-2`, then `F-LAUNCH-1`.** Neither is the most scientifically
interesting question here — `Q-LIT-1` and `Q-ISO-1` are — but they are the ones
whose answers change *where other people's work lands*. Deciding them late does
not delay one item; it risks invalidating a batch of completed repairs, and in
`F-LAUNCH-2`'s case it risks running a campaign whose treatment was never
delivered.

**I have deliberately not chosen an entrypoint or proposed a launcher design.**
All twelve resolved values are recorded in `F-LAUNCH-1`, and the arm semantics
in `F-LAUNCH-2`, so both decisions are made explicitly rather than by
implication.

---

## §4 CONSOLIDATED FROZEN-PARAMETER TABLE — **DRAFT 1, for Supervisor cross-check**

**Purpose:** the operator never assembles a value from Parts 1–8. Every
behaviourally relevant campaign parameter appears here once, with its authority.

### 4.0 How to read the two rightmost columns — **read this before the table**

`CLASS` is one of: **`FIXED`** · **`DISABLED`** · **`NULL`** ·
**`AGENT_CONTROLLED`** · **`PROVIDER_CONTROLLED`** · **`HARDWARE_DERIVED`**.

`EFFECTIVE?` is the column that matters, and it exists because **this campaign
has already been bitten three times by a stated authority that was not the
effective one** — `H100_CORESIDENCY_FACTOR` empty, `runtime_profiles.yaml` with
no H100 row silently resolving to `watchdog_enabled=False`, and typed portions
dead in transit until #320.

| marker | meaning |
|---|---|
| **`VERIFIED`** | the code path that consumes this value has been read, and it reads *this* authority |
| **`STATED`** | the campaign declares it; **the consuming code path has NOT been confirmed to read it** |
| **`GAP`** | **known NOT to be effective today** — a tracked implementation gap |
| **`PENDING-HW`** | value or effectiveness awaits hardware qualification |

> **A `STATED` row is not a claim that the parameter works. It is a claim that
> the campaign has declared it and nobody has yet checked the consumer.** Those
> rows are the Supervisor's cross-check queue, and I expect some to come back as
> `GAP`. That is the mechanism working.

### 4.0a ⚠️ WHICH LAUNCHER — this determines whether any other row is even pointed at the right file

**The band fleet invokes `launch_prior_baseline_experiment.sh`, NOT
`launch_v20_campaign.sh`** (`launch_band_fleet.sh:59`). Verified this lane.

**`launch_prior_baseline_experiment.sh` passes NONE of the twelve campaign
parameters** — not one of `trial_portion` · `train_portion` · `eval_portion` ·
`formal_portion` · `formal_train_portion` · `formal_eval_portion` ·
`max_rounds` · `max_epochs` · `skip_formal_min_delta` ·
`bypass_formal_time_budget_min_delta` · `trial_time_budget_minutes` ·
`formal_time_budget_minutes`.

**So on the actual campaign path every one of those resolves to a
`_chain_common.sh` default**, and after #320 three of them are a **tri-state**:

```text
_chain_common.sh:85-87   TRIAL_PORTION="" TRAIN_PORTION="" EVAL_PORTION=""
                         empty == omit == AGENT_CONTROLLED
                         typed == EXPERIMENT_FIXED via the plan_overrides lock
```

> **The `plan_overrides` lock genuinely binds — and on the campaign path nothing
> feeds it.** The mechanism is present and unused. Trial portions are therefore
> **`AGENT_CONTROLLED` today**, not `0.1/0.1/0.1` and not the `0.02` schema
> fallback either.

**This is the stated-versus-effective distinction one level deeper: the
*mechanism* is verified, the *campaign's use of it* is absent.** A row can be
`VERIFIED` at the consumer and still `GAP` at the campaign.

**Consequence for the repair work:** fixing values in `launch_v20_campaign.sh`
would repair a launcher the campaign never calls. **`ROW-L` below is therefore a
prerequisite for interpreting rows 9, 19–26, 31, 33–35, 56, 57.**

| # | parameter | value | authority | class | effective? | blocks |
|---|---|---|---|---|---|---|
| **L** | **campaign launcher entrypoint** | **UNDECIDED** — band fleet calls `launch_prior_baseline_experiment.sh`, which types nothing | none yet | FIXED | **GAP** | **PRE-TAG** |

### 4.1 Campaign identity and topology

| # | parameter | value | authority | class | effective? |
|---|---|---|---|---|---|
| 1 | campaign arms executed | **GOLD ONLY** | `D-CAMP-1` | FIXED | STATED |
| 2 | Blind required for Gold launch/completion/finalization | **false** | `D-CAMP-1` | FIXED | STATED |
| 3 | formal GPU count | **4** | `D-HW-5` | HARDWARE_DERIVED | **VERIFIED** — `A-HW-VERIFY-1` measured 4 × H100 80GB HBM3 |
| 4 | GPU type | **H100_SXM** | `D-HW-5` | HARDWARE_DERIVED | **VERIFIED** |
| 5 | GPU residency | **EXCLUSIVE_SINGLE_BAND** | `D-HW-5` | FIXED | STATED |
| 6 | band → GPU map | 0-3→GPU0 · 4-9→GPU1 · 10-14→GPU2 · 15-19→GPU3 | `D-HW-5` | FIXED | STATED |
| 7 | bands | `0-3`, `4-9`, `10-14`, `15-19` | `D-TASK-7` | FIXED | **VERIFIED** — `launch_band_fleet.sh:64` |
| 8 | host sharing | **shared with other tenants**, ~23–30 % baseline, time-varying | measured | PROVIDER_CONTROLLED | **VERIFIED** — two readings |

### 4.2 Search budget

| # | parameter | value | authority | class | effective? |
|---|---|---|---|---|---|
| 9 | `num_iterations` per band | **20** | `D-BUD-2` | FIXED | **GAP** — launchers pass 10 |
| 10 | band-local early stop (FCNet + 2.0) | **PENDING** | `D-BUD-17` | FIXED | **GAP** — blocked on `A2-FCNET`; no per-band FCNet reference exists |
| 11 | `max_rounds` | **3**, formal is the last | `D-BUD-3` | FIXED | **VERIFIED** |
| 12 | `attempts_per_round` | **3** | `D-BUD-4` | FIXED | **VERIFIED** |
| 13 | `attempts_per_formal_round` | **5** | `D-BUD-4` | FIXED | **VERIFIED** |
| 14 | `max_fail_rounds` | **3** | `D-BUD-4` | FIXED | **VERIFIED** |
| 15 | `max_proposal_attempts` | **3** | `D-BUD-4` | FIXED | **VERIFIED** |
| 16 | `max_impl_attempts` | **3** | `D-BUD-4` | FIXED | **VERIFIED** |
| 17 | campaign token cap | **NONE** | `D-BUD-15` | NULL | **VERIFIED** — no such mechanism exists |
| 18 | campaign spend cap | **NONE** | `D-BUD-15` | NULL | **VERIFIED** |

### 4.3 Data and evaluation scope

| # | parameter | value | authority | class | effective? |
|---|---|---|---|---|---|
| 19 | trial `trial_portion` | **0.10** | `D-BUD-7` | FIXED | **GAP / PRE-TAG** — lock BINDS (Supervisor-verified) but the campaign launcher types nothing; `_chain_common:85` is `""` = AGENT_CONTROLLED |
| 20 | trial `train_portion` | **0.10** | `D-BUD-7` | FIXED | **GAP / PRE-TAG** — same |
| 21 | trial `eval_portion` | **0.01** | `D-BUD-7` | FIXED | **GAP / PRE-TAG** — same |
| 22 | → effective trial training | **1 %** | derived | FIXED | **GAP / PRE-TAG** — currently agent-chosen |
| 23 | formal `formal_portion` | **1.0** | `D-BUD-8` | FIXED | **GAP / PRE-TAG** — `_chain_common:138` = `0.1` (inverted) |
| 24 | formal `formal_train_portion` | **0.10** | `D-BUD-8` | FIXED | **GAP / PRE-TAG** — `_chain_common:139` = `1.0` (inverted) |
| 25 | formal `formal_eval_portion` | **0.10** | `D-BUD-8` | FIXED | **GAP / PRE-TAG** — `_chain_common:101` = `1.0` (inverted) |
| 26 | → effective formal training | **10 %** | derived | FIXED | **GAP / PRE-TAG** — same volume, DIFFERENT per-epoch sampling |
| 27 | terminal champion evaluation | **100 %**, per band, after selection freezes | `D-BUD-9` | FIXED | **GAP** — no champion re-evaluation exists |
| 28 | canonical data | testpod `TIDMAD_DATA`, 84 G, 40 h5 | `D-DATA-1` | FIXED | **VERIFIED** — Q3 manifest `39270b45…33ad85` |
| 29 | train ordering | **sequential, `shuffle=false`** | `D-RAND-1` | FIXED | **STATED** — `A3-1` |
| 30 | segmentation size | **40,000** | `D-ACT-7` | FIXED | **VERIFIED** — `legacy_baseline_configs.json`, corroborated ×2 |

### 4.4 Training and resource ceilings

| # | parameter | value | authority | class | effective? |
|---|---|---|---|---|---|
| 31 | trial `max_epochs` | **2** | `D-BUD-6` | FIXED | **GAP** — one mode-agnostic knob exists; launchers pass 1 |
| 32 | formal `max_epochs` | **1** | `D-BUD-6` | FIXED | **VERIFIED** |
| 33 | trial time ceiling | **30 min** | `D-HW-7` | HARDWARE_DERIVED | **GAP / PRE-TAG** — `_chain_common:99` is `""`: the campaign path passes **NO time budget at all**, so there is no pre-flight gate. Value also `PENDING-HW` |
| 34 | formal time ceiling | **120 min** | `D-HW-7` | HARDWARE_DERIVED | **GAP / PRE-TAG** — `_chain_common:100` is `""`; `operator_budget_seconds` is `None` even on formal rounds. Value also `PENDING-HW` |
| 35 | bypass formal time ceiling | **200 min** | `P7-C` | HARDWARE_DERIVED | **GAP** — bypass moves the forecast only, not the watchdog deadline |
| 36 | scientific VRAM ceiling | **60 GB** | `D-HW-6` | FIXED | **GAP** — posture ships 18 GiB/chain; **GB vs GiB unsettled** |
| 37 | watchdog | **REQUIRED** | `D-BUD-13` | HARDWARE_DERIVED | **GAP** — `F-H100-WD-1`: no H100 row, resolves `watchdog_enabled=False` |
| 38 | early stopping (loss-based) | **none exists** | audited | DISABLED | **VERIFIED** |

### 4.5 Agent action space

| # | parameter | value | authority | class | effective? |
|---|---|---|---|---|---|
| 39 | architecture | free within contracts | `D-ACT-1` | AGENT_CONTROLLED | STATED |
| 40 | model size | 10M–500M encouraged, **no hard bound** | `D-ACT-2` | AGENT_CONTROLLED | STATED |
| 41 | loss / objective | free, task-contract compatible | `D-ACT-4` | AGENT_CONTROLLED | STATED |
| 42 | optimizer | free within current support | `D-ACT-5` | AGENT_CONTROLLED | **STATED** — resolved list not yet materialized (`A5-4`) |
| 43 | scheduler | free within current support, incl. none | `D-ACT-6` | AGENT_CONTROLLED | STATED — `A5-4` |
| 44 | batch size, lr, weight decay, dropout, dims | free | `D-ACT-7` | AGENT_CONTROLLED | STATED |
| 45 | pretrained weights / warm start | **DISABLED** | `D-ACT-3` | DISABLED | **STATED** — enforcement unverified |
| 46 | ensembles | **NOT INTRODUCED** | `D-ACT-9` | DISABLED | STATED |
| 47 | preprocessing expansion | **NOT INTRODUCED** | `D-ACT-10` | DISABLED | STATED |
| 48 | environment mutation (pip/conda/downloads) | **DISABLED** | `D-ACT-12` | DISABLED | **STATED** — `A5-6`, likely absent-by-convention |
| 49 | evaluation authority | agent may **NOT** modify | `D-ACT-11` | FIXED | **STATED** — `A5-3`, structural enforcement unverified |

### 4.6 Scoring, validity, selection

| # | parameter | value | authority | class | effective? |
|---|---|---|---|---|---|
| 50 | ranking authority | **Golden Metric only**, no tie-break | `D-SCORE-1` | FIXED | **VERIFIED** |
| 51 | aggregation | `log_5.27(Σ per-segment / Σ|S_f|)` | `scoring_utils` §3 | FIXED | **VERIFIED** |
| 52 | HealthGate role | independent validity authority | `D-SCORE-2` | FIXED | **VERIFIED** |
| 53 | required blocking gates | all must pass | `D-SCORE-2` | FIXED | **VERIFIED** |
| 54 | per-file aggregation | **`all_pass`** | `D-SCORE-3` | FIXED | **GAP** — ships `any_pass` |
| 55 | HealthGate thresholds | **unchanged, no tuning** | `D-SCORE-2` | FIXED | **VERIFIED** |
| 56 | `skip_formal_min_delta` | **−2.0** | `P6-A` | FIXED | **GAP / PRE-TAG** — `_chain_common:69` = `−1.0` |
| 57 | `bypass_formal_time_budget_min_delta` | **+0.5** | `P6-B` | FIXED | **GAP / PRE-TAG** — `_chain_common:70` = `0.0` |
| 58 | formal incumbent cold start | worst sentinel until a valid FORMAL result | `P7-D` | FIXED | **VERIFIED** |
| 59 | official trajectory | cumulative best HealthGate-valid **FORMAL** by iteration | `D-SCORE-7` | FIXED | **GAP** — `best_*` fields mix trial+formal (`D-SCORE-5`) |
| 60 | Composed Best | ONE `score_vector` over scope `0..19` | `D-BEST-1` | FIXED | **GAP** — not implemented |
| 61 | Strict Best | retrain per band, ONE `score_vector` over `0..19` | `D-BEST-2` | FIXED | **GAP** — not implemented |

### 4.7 LLM configuration

| # | parameter | value | authority | class | effective? |
|---|---|---|---|---|---|
| 62 | routing file | `llm_configs/openai_tiered_pro.json` | `D-LLM-1` | FIXED | **VERIFIED** — sha256 `fc3d95ec…9475` |
| 63 | API surface | **Chat Completions** | `D-LLM-1` | FIXED | **VERIFIED** — 3 call sites |
| 64 | model, 8 workflow roles | `gpt-5.5` | `D-LLM-1` | FIXED | **VERIFIED** |
| 65 | model, `lit_review` ×2 | `deepseek-v4-pro` | `D-LLM-1` | FIXED | VERIFIED — disposition pending `Q-LIT-1` |
| 66a | immutable snapshot pin (config) | `gpt-5.5-2026-04-23` | `D-LLM-13` | FIXED | **GAP / RELEASE BLOCKER** — operator-ruled 2026-08-26; assigned Lane E |
| 66b | **capture the provider's RESOLVED model into provenance** | `response.model` | `D-LLM-13` | FIXED | **GAP / RELEASE BLOCKER** — operator-ruled; witness = request A, resolve B, prove provenance records **B** not an echo of A. See §4.12 |
| 67 | reasoning effort | **HIGH** | `D-LLM-4` | FIXED | **GAP** — nothing sent; omitted ≠ high (probe-confirmed) |
| 68 | temperature | **not tunable** on this model | `D-LLM-5` | PROVIDER_CONTROLLED | **VERIFIED** — probe: only default 1 |
| 69 | top_p | **unsupported** on this model | `D-LLM-5` | PROVIDER_CONTROLLED | **VERIFIED** — probe: 400 |
| 70 | LLM seed | **PROVIDER_CONTROLLED_STOCHASTICITY** | `D-LLM-6` | PROVIDER_CONTROLLED | **VERIFIED** — probe: accepted but inert, no fingerprint |
| 71 | request timeout | **600 s** | `D-LLM-12` | FIXED | **VERIFIED** |
| 72 | retry, 429 / 5xx | **indefinite** | `D-LLM-12` | FIXED | **VERIFIED** |
| 73 | retry, timeout / connection | **indefinite** | `D-LLM-12` | FIXED | **GAP** — bounded at 3 (`F-LLM-2`, open) |
| 74 | model fallback | **DISABLED** | `D-LLM-3` | DISABLED | **VERIFIED** |
| 75 | provider-side tools | **NOT_APPLICABLE** | `D-LLM-10` | DISABLED | **VERIFIED** — zero production callers |
| 76 | account rate limits | 10,000 RPM · 4,000,000 TPM | measured | PROVIDER_CONTROLLED | **VERIFIED** |

### 4.8 Randomness

| # | parameter | value | authority | class | effective? |
|---|---|---|---|---|---|
| 77 | per-band seeds A/B/C/D | distinct, frozen pre-launch | `D-RAND-3` | FIXED | **GAP** — literal values not yet chosen |
| 78 | per-round derivation | `f(campaign_seed, band, round, purpose)` | `D-RAND-4` | FIXED | STATED |
| 79 | RNG authority coverage | 8 named surfaces | `D-RAND-5` | FIXED | **STATED** — `A3-2` |
| 80 | agent trajectory | not synchronized | `D-RAND-7` | AGENT_CONTROLLED | **VERIFIED** |
| 81 | bitwise-deterministic CUDA | **NOT REQUIRED** | `D-RAND-9` | DISABLED | **STATED** — `A3-4` |

### 4.9 Treatment

| # | parameter | value | authority | class | effective? |
|---|---|---|---|---|---|
| 82 | Gold advice artifact | immutable, hashed, every proposer round | `D-TREAT-1/2` | FIXED | **GAP** — not authored; launcher refuses advice in both arms (`T-IMPL-1`) |
| 83 | prior-baseline artifact | immutable, hashed, quantitative only | `D-TREAT-3` | FIXED | GAP |
| 84 | injection point | **proposer only** | `D-TREAT-4B` | FIXED | GAP |
| 85 | byte-identity across 4 Gold bands | required | `D-TREAT-8` | FIXED | GAP |
| 86 | excluded baseline assets | weights, code, exact recipes | `D-TREAT-4` | DISABLED | STATED |
| 87 | Blind config | frozen control definition **even if Blind never runs** | `D-TREAT-5` | DISABLED | STATED — §7 of this package |

### 4.10 Failure accounting

| # | parameter | value | authority | class | effective? |
|---|---|---|---|---|---|
| 88 | scientific failure | consumes scientific budget | `D-FAIL-1/5` | FIXED | **VERIFIED** |
| 89 | infrastructure failure | consumes **no** scientific budget | `D-FAIL-1/5` | FIXED | **GAP** — API failure consumes an attempt (`A8-1`) |
| 90 | ceiling breach classification | **SCIENTIFIC / RESOURCE_INFEASIBLE** | `D-FAIL-4` | FIXED | STATED |
| 91 | mid-training checkpoint resume | **none** | `D-FAIL-3` | DISABLED | **VERIFIED** — no per-epoch checkpointing exists |
| 92 | resume | provenance-exact, fail-closed | `D-FAIL-7` | FIXED | **GAP** — `formal_eval_portion` not in `_CANONICAL` |
| 93 | transactional success | exit 0 is **not** success | `D-FAIL-8` | FIXED | **GAP** — `no_records` path exits 0 |
| 94 | failure locality | band-local; never kill healthy work | `D-FAIL-6` | FIXED | STATED |

### 4.12 Why row 66 has two halves — a provenance field that cannot fail

**Verified in source, this lane, 2026-08-26**, on the Supervisor's finding:

```text
grep 'response.model | resolved_model' agent/llm_bridge.py   ->  NOTHING
_record_usage(model_name=...)                                ->  the CONFIGURED value, passed by the caller
persisted token_usage row                                    ->  "model": "gpt-5.5"     (the ALIAS)
live probe of the same request shape                         ->  "gpt-5.5-2026-04-23"   (the SNAPSHOT)
```

**The provider returns the resolved snapshot on every call and SIDERIUS discards
it.**

**Why pinning alone is not enough, stated precisely.** After the config pin, the
persisted record would read `gpt-5.5-2026-04-23` — **but that is the configured
value being echoed back, not the served model being observed.** If the provider
served something else, **the record would read exactly the same.**

> **A provenance field that records what you asked for, rather than what you
> got, cannot discriminate between the two cases — so it can never fail.** By
> the campaign's own anti-vacuity rule, a check that cannot fail is not a check.

That is the same stated-versus-effective defect this entire gate exists to
eliminate, and it would arrive in this very table as a `VERIFIED` row that was
really `STATED`. **Row 66 is therefore split: 66a pins, 66b makes the pin
checkable.**

**This is a CLASS, not a one-off.** Any provenance field that *echoes
configuration* rather than *capturing observation* has this property. The
distinction is already visible in this table: **row 62's config sha256 is an
observation** — computed from the file's bytes, so it fails if the file changes.
**Row 66b's model identity must be an observation too.** §11's adversarial
witnesses should test the class, not just this instance.

#### 4.12a Latent, not live — recorded without expanding scope

`agent/llm_bridge.py:443-444` — `if model_id is None and known: model_id =
known['default_model']`, and openai's default is **`gpt-4o`**: not merely a
mutable alias but a **different model**, substituted **silently, with no
warning**.

**Unreachable on any campaign path** — the routing file supplies `model_id` for
all 10 roles, and the only no-`model_id` constructions are in `env_validation/`.
Recorded as **latent**, deliberately **not** expanded into a framework redesign.
It becomes live only if a role is ever added without a `model_id`.

### 4.13 Operator rulings of 2026-08-26 — the triage axis and the two rules that govern every GAP

Relayed by the Supervisor; recorded here because §4 is the campaign's single
deduplicated blocker ledger and the operator asked that no second one be created.

**Every GAP now carries a disposition**, and **only the first enters the pre-tag
critical path**:

| disposition | meaning |
|---|---|
| **RELEASE BLOCKER** | must be repaired before the `v0.1.0` tag |
| **POST-TAG GOLD QUALIFICATION** | measured/frozen after the tag, before the Gold launch |
| **ACCEPTED NON-BLOCKING** | recorded, deliberately not repaired |
| **CONDITIONAL_ON_BLIND** | resolved only by blind-arm execution |
| **ICLR-FUTURE** | out of scope for the arXiv release |

> **The symmetric warning, quoted:** *do not downgrade a behaviorally relevant
> mismatch just to shorten the list.*

**Rule 1 — direction of repair (operator, verbatim):**

> *"Do not reinterpret the frozen policy to fit the launcher. Repair the
> launcher/effective consumer path."*

**Rule 2 — the witness standard (operator):** proof must inspect **effective
resolved values after all override, planner and carrier logic has run.** Source
text, CLI declarations and config presence are **explicitly not proof**.

> **Rule 2 is what makes §4.0a decisive rather than pedantic.** A repair verified
> against `launch_v20_campaign.sh` source text satisfies neither rule: it is
> source text, not an effective resolved value, and it repairs a launcher the
> effective consumer path never invokes. **All effective-config mismatches are
> RELEASE BLOCKERS — but they must be repaired on the path the campaign
> actually executes.**

**Ruling on all effective-config mismatches:** RELEASE BLOCKERS — not rows 23–26
alone. That sweeps in rows 19–22, 33, 34, 56, 57 and row L.

#### 4.13a `F-H100-WD-1` splits — the numeric measurement is POST-TAG, its SUPPORT is not

**Route B ruled.** Numeric H100 calibration is
`HARDWARE_DERIVED / EXPLICIT / OBSERVED / IMMUTABLE FOR THE CAMPAIGN ONCE
QUALIFIED`, bound by the package as a content-hashed artifact, its identity and
hash shown in the final operator review. The measurement campaign stays **off**
the pre-tag critical path.

**But the operator set a pre-tag boundary test** — *if making the official Gold
run consume the hardware-derived artifact requires changing tracked code, that
smallest support repair happens BEFORE `v0.1.0`. Do not measure first and
discover after tag that the software must change.* The Supervisor ran it
mechanically. **The released system fails it on three counts:**

| # | failure | evidence |
|---|---|---|
| 1 | **invisible default** | the overlay is consumed because `calibration_dir()` happens to contain `runtime_profiles_<gpu_slug>.json`. No explicit launch binding exists — verbatim the prohibited case |
| 2 | **no hash identity** | zero hash lines in `watchdog_profile.py`; positive control `health_config_sha256` appears in 70 files elsewhere. Nothing persists WHICH profile a run used |
| 3 | **fail-open** | `_load_measured` returns `{}` when absent → resolution proceeds to shipped/`UNCALIBRATED` → **watchdog silently OFF**. (Malformed content DOES refuse loudly — that half is already correct) |

> **This is exactly the third element I asked for when answering Route A vs B,
> reached independently and mechanically.** Failure 3 is `F-H100-WD-1`
> reproducing itself through the very artifact meant to fix it: bind an overlay,
> forget to ship it, and the run proceeds with no watchdog and says nothing.

| # | parameter | value | authority | class | effective? |
|---|---|---|---|---|---|
| **W** | **explicit, hash-verified binding of the runtime-calibration artifact** | opt-in path + expected `sha256`; verified BEFORE consumption; declared-but-missing or mismatched **REFUSES**; resolved identity+hash persisted to run provenance; launch manifest names the artifact | operator ruling 2026-08-26 (`F-H100-WD-1-PRETAG`) | FIXED | **GAP / RELEASE BLOCKER** |

Undeclared behaviour stays byte-identical — **presence-keyed**, the
task-composition transport precedent from PR-12bc. The *numeric* row this
supports (rows 33/34 ceiling values) stays **POST-TAG GOLD QUALIFICATION**.

#### 4.13b Compute rule for the runbook — stated as a pair, never separately

> **Engineering qualification uses minimum semantic compute. Formal Gold
> scientific execution is the only place the full frozen scientific opportunity
> budget is actually consumed.**

Both halves go in the runbook together, so that **nobody reads a 30-minute
ceiling as a 30-minute test target.**

### 4.11 What this table already shows

**95 rows. 30 `VERIFIED`. 20 `GAP` — known not effective today. 3
`PENDING-HW`. The remainder `STATED`, awaiting the Supervisor's cross-check.**

**The 19 `GAP` rows are the Gold launch's real work list**, and they are not
evenly distributed: they cluster in **treatment injection** (82–85, none of it
built), **formal portions** (23–26, values inverted vs the launchers),
**selection** (59–61, Composed/Strict Best unimplemented), and **runtime
enforcement** (35–37, the watchdog disabled on the target hardware).

**No row is marked `VERIFIED` on this lane's say-so where the claim is about
code behaviour.** Rows 3, 4 and 8 are Supervisor measurements; rows 68–70 and 76
are live API probes; the rest of the `VERIFIED` set are source reads recorded
with file:line in the ledger and open to challenge.

---

## §6 GAP DISPOSITION — the deduplicated blocker ledger

Per `D-GOV-9`. Every GAP in §4 carries exactly one disposition. **Only
`RELEASE BLOCKER` enters the pre-tag critical path.** The operator's symmetric
constraint governs the whole table: *do not downgrade a behaviorally relevant
mismatch just to shorten the list.*

### 6.0 ⚠️ The axis has five categories and this campaign has six kinds of GAP

**I am flagging this rather than force-fitting.** Four GAPs are neither
framework-code defects nor hardware measurements — they are **campaign content
that does not exist yet**: the per-band seed literals, the Gold advice artifact,
the prior-baseline artifact, and the FCNet per-band reference. Nothing in the
framework must change for them; somebody must *author or measure* them before a
Gold launch.

Mapping them to `POST-TAG GOLD QUALIFICATION` would be reasonable-sounding and
wrong in one specific way: that category exists to keep the **hardware
measurement campaign** off the pre-tag path, and it carries the connotation
*"will be produced by qualification."* These will not be. They will be produced
by me, and if they are silently filed under a hardware category they can reach
the Gold launch unauthored.

**ENDORSED by the Supervisor 2026-08-26 — the label names an existing gate
rather than inventing one.** The Part-7 completion criteria already hold
**PACKAGE FREEZE (criterion B)** separate from the **CODE TAG (criterion D)**.
These four items are package-content blockers anchored to **B**; the POST-TAG
items are hardware measurements anchored to qualification. The categories were
already distinct in the completion criteria — the axis simply had no name for
one of them.

**Tiebreak rule, now recorded on both sides:** *fold **UP** to `RELEASE
BLOCKER`, never **down** to `POST-TAG`.*

**So I use a sixth label, `GOLD LAUNCH PRECONDITION`.** It
is not a downgrade — every item under it still blocks the Gold launch
absolutely. It is a *routing* distinction: `RELEASE BLOCKER` routes to the
Supervisor's implementation lanes, `GOLD LAUNCH PRECONDITION` routes to me.
**If the operator prefers five categories, fold these into `RELEASE BLOCKER`,
not into `POST-TAG`** — the failure mode of over-blocking is a delayed tag; the
failure mode of under-blocking is a scientifically void campaign.

Note the precedent: I originally classified `D-LLM-13` as a `GOLD LAUNCH
PRECONDITION` and the operator **overrode it to `RELEASE BLOCKER`**. That
override is exactly the direction of error I am guarding against here, and it is
why I am not applying the label to anything that touches tracked code.

### 6.1 RELEASE BLOCKER — pre-tag critical path

| § | row | gap | why it blocks | routing |
|---|---|---|---|---|
| **A0** | **`F-LAUNCH-2`** | **no existing launcher implements this campaign's experiment** | **the treatment is refused in both arms; two further confounds; wrong pinned `experiment_arm`** | **operator decision — §3.0** |
| A | **L** | campaign launcher entrypoint UNDECIDED | **prerequisite for §6.1 B and C** — repairs landed in the wrong launcher satisfy neither governing rule | **operator decision first** |
| B | 19–22 | trial portions untyped ⇒ AGENT_CONTROLLED | frozen `EXPERIMENT_FIXED` values are not fixed; the search budget is agent-chosen | effective-config |
| B | 23–26 | formal portions inverted | same volume, **different per-epoch sampling** — behaviorally relevant | effective-config |
| B | 9 | `num_iterations` 10 vs frozen 20 | halves the frozen scientific opportunity budget | effective-config |
| B | 31 | trial `max_epochs` 1 vs frozen 2 | **also a missing capability** — one mode-agnostic knob exists, so "trial epochs" is not separately expressible | capability + effective-config |
| B | 56 | `skip_formal_min_delta` −1.0 vs −2.0 | changes which candidates reach a formal round | effective-config |
| B | 57 | `bypass_formal_time_budget_min_delta` 0.0 vs +0.5 | same | effective-config |
| C | 33s/34s | **no time budget is passed at all** | not a wrong ceiling — **no pre-flight gate exists**, `operator_budget_seconds` is `None` even on formal rounds | support half only |
| C | 35s | bypass moves the forecast, not the watchdog deadline | a frozen 200-min bypass ceiling that no enforcement layer honours | support half only |
| C | 36u | **`GB` vs `GiB` unsettled** at the 60/18 boundary | a unit ambiguity at a resource ceiling decides what fits; must be settled **before** qualification measures against it | **operator question** — see §6.1b |
| C | **W** | runtime-calibration artifact has no explicit hash-verified binding | `F-H100-WD-1-PRETAG`; fail-open ⇒ watchdog silently OFF | Lane E (assigned) |
| C | 37s | watchdog REQUIRED but resolves `enabled=False` | the support is row W; see §4.13a | subsumed by W |
| D | 54 | ships `any_pass`, frozen `all_pass` | **lenient across files** — changes which rounds are classified valid | effective-config |
| D | 59 | `best_*` fields mix trial + formal pools | the official trajectory would be reported off a mixed pool | scientific correctness |
| D | 27 | no champion re-evaluation at 100 % exists | **the headline number cannot be produced** | missing capability |
| D | 60 | Composed Best not implemented | headline scientific claim | missing capability |
| D | 61 | Strict Best not implemented | headline scientific claim | missing capability |
| E | 66a | snapshot pin absent | operator-ruled 2026-08-26 | Lane E (assigned) |
| E | 66b | served-model identity never captured | operator-ruled; makes 66a checkable at all | Lane E (assigned) |
| E | 67 | reasoning effort never sent | frozen `HIGH`; **omitted ≠ high**, probe-confirmed | effective-config |
| E | 73 | retry bounded at 3, frozen indefinite | **coupled to row 89** — an exhausted retry consumes a scientific attempt | `F-LLM-2` open |
| F | 89 | API failure consumes a scientific attempt | directly violates frozen `D-FAIL-1/5` | scientific correctness |
| F | 92 | `formal_eval_portion` absent from `RunInvariants._CANONICAL` | two iterations at different formal eval scopes fold into one incumbent **with no refusal** | fail-closed resume |
| F | F | 93 | `no_records` path exits 0 | exit 0 is not success | **Lane C #315 discharges it — §6.1a** |
| B | 82 | launcher refuses advice **in both arms** (`T-IMPL-1`) | **the treatment cannot be delivered** — framework half of row 82. **VERIFIED** `launch_prior_baseline_experiment.sh:142-146` | **joins `F-LAUNCH-1`** |

**Count: 31 rows across 26 entries** — `F-LAUNCH-2` added 2026-08-26. Rows 33/34/35/36/37 contribute their
**support** half here and their **numeric** half to §6.2.

**Row 82's framework half moved into group B on Supervisor verification.**
`launch_prior_baseline_experiment.sh:142-146` hard-refuses `--advice` /
`--human_advice_file` **in both arms** — correct for X9, where advice was a
confound; fatal for Gold, where **advice IS the treatment**. Because the
entrypoint ruling decides where the flag must be accepted, it is part of the
same work item rather than a thirteenth ticket. *(Same file's header still
memorializes the superseded 4-coresident topology; the `F-LAUNCH-1` repair
should sweep that prose.)*

#### 6.1a Row 93 — the repair exists and is unmerged

`fix/failure-honesty-exit-status` carries three commits that are **not ancestors
of `origin/master`** (verified):

```text
090e601b  fix(F8):    a chain's exit status must reflect its iterations' failures
d9c08404  fix(F13):   a round that ran zero optimizer steps must not be reported as progress
df3f1c04  fix(F-Q5-1): the probe assembler must honour the failure contract it states
```

**Confirmed by the Supervisor: `fix/failure-honesty-exit-status` IS Lane C's
#315 branch.** So #315 landing discharges row 93 — this **raises the priority of
an existing queue item rather than adding work**, and the Supervisor will verify
discharge at merge rather than assume it.

**This is routing, not authoring.** F8 is row 93 directly. F13 is adjacent to
rows 89/93 — a round that ran zero optimizer steps being counted as progress is
the same honesty class one layer in. I have **not** verified that these three
fully discharge rows 89/93; I am recording that a candidate repair exists so the
Supervisor does not commission a second one.

#### 6.1b Row 36 — `GB` vs `GiB` goes to the operator, decided by neither lane

Neither the Supervisor nor I may settle this: it is a **numeric resource
ceiling**, `EXPERIMENT_FIXED`, so it is an operator decision. Recorded with the
Supervisor's recommendation and the arithmetic, so the operator decides against
numbers rather than a preference:

| | |
|---|---|
| recommendation | **`GiB`** — the repo's canonical `_GB = 1024**3` authority; the ruling's own *"use the existing canonical unit"* |
| the delta | **60 GiB = 64.4 GB** |
| the card | an 80 GB H100 is **79.6 GiB** |
| headroom under `GiB` | **19.6 GiB** |

**It must be settled before qualification runs**, or the measurement targets an
undefined number and its result cannot be compared to the frozen ceiling.

### 6.2 POST-TAG GOLD QUALIFICATION — off the pre-tag path

| row | gap | why post-tag |
|---|---|---|
| 33n | trial ceiling **30 min** numeric | `HARDWARE_DERIVED`; Route B ruled |
| 34n | formal ceiling **120 min** numeric | same |
| 35n | bypass ceiling **200 min** numeric | same |
| 36n | scientific VRAM ceiling **60** numeric | same, **once the unit is settled** (§6.1 C) |
| 37n | watchdog H100 profile row | measured under qualification, bound via row W |

Each becomes `HARDWARE_DERIVED / EXPLICIT / OBSERVED / IMMUTABLE FOR THE
CAMPAIGN ONCE QUALIFIED`, content-hashed, identity shown in the final operator
review.

### 6.3 GOLD LAUNCH PRECONDITION *(proposed sixth category — see §6.0)*

**Routes to me, not to an implementation lane. Blocks the Gold launch
absolutely.**

| row | gap | what must happen |
|---|---|---|
| 77 | per-band seeds A/B/C/D | literal values chosen and frozen pre-launch |
| 82 | Gold advice artifact | authored, immutable, hashed *(framework half is a RELEASE BLOCKER — §6.1 G)* |
| 83 | prior-baseline artifact | authored, quantitative only, hashed |
| 10 | band-local early stop reference | blocked on `A2-FCNET` — four per-band FCNet scores |

### 6.4 CONDITIONAL_ON_BLIND

| row | gap | resolved by |
|---|---|---|
| 84 | injection point = proposer only | blind-arm execution proves the injection surface is the only one |
| 85 | byte-identity across the 4 Gold bands | verified at launch, across arms |

### 6.5 ACCEPTED NON-BLOCKING

| item | why |
|---|---|
| `gpt-4o` fallback, `llm_bridge.py:443-444` | operator-ruled **NON-BLOCKING LATENT** unless reachability changes |

### 6.6 ICLR-FUTURE

**Empty.** Nothing has been deferred out of the arXiv release. Recorded as
empty rather than omitted, so its emptiness is a statement and not an oversight.

### 6.7 What the triage shows

**25 RELEASE BLOCKER entries, 5 POST-TAG, 4 GOLD LAUNCH PRECONDITION, 2
CONDITIONAL_ON_BLIND, 1 ACCEPTED, 0 ICLR-FUTURE.**

**Thirteen of the twenty-five reduce to a single path** (rows 9, 19–26, 31, 56,
57, the two time-budget supports, and **row 82's framework half**). They are not
thirteen independent defects — they are **one defect**, `F-LAUNCH-1`: the
launcher the campaign actually calls types none of them, and refuses the
treatment flag in both arms. If row L resolves to the band-fleet path, that is
one coherent work item, and the blocker count falls **from 25 to 13** without a
single value being downgraded.

**Six are missing capabilities, not mismatches** (rows 27, 31, 60, 61, 66b, and
row W). No amount of launcher repair reaches them; each needs code that does not
exist. Rows 27, 60 and 61 are the ones that produce the campaign's headline
numbers, which makes them the longest genuine pole in this table.

## §7 SCORING, VALIDITY AND FINAL SELECTION

**This section states what the campaign will actually compute, what it will
refuse to compute, and where the two currently disagree.**

### 7.1 The Golden Metric is the task definition

The scalar is

```text
score = log_5.27( Σ_{f,i} (snr_sg / s_max)·snr_squid  /  Σ_f |S_f| )
```

`score_vector` returns `(file_vector, scalar)` and is the **one** arithmetic
authority (`execute_tools/scoring_utils.py:549`, arithmetic at `:732` and
`:739-743`). No production call site re-inlines it.

> **The metric is never modified to make a result look better.** If a score
> looks wrong, the conformance of the pipeline is audited — the formula is not
> renegotiated. This is why every finding below is phrased as *"the pipeline
> departs from the metric"* and never as *"the metric should change."*

### 7.2 The forbidden aggregations — and why one of them is our band partition

`scoring_utils.py:24-29` names three invalid constructions:

1. mean of per-file **log** scores
2. mean of per-band **log** scores
3. mean of per-band **linear** means — *"e.g. 4/6/5/5"*

**Our band partition is 4/6/5/5.** The prohibition names this campaign's
geometry explicitly, which is not a coincidence: it is the construction someone
reaches for the moment a run is split into bands.

**The only valid cross-band number is ONE `score_vector` call over scope
`0..19`.** A working, verified precedent exists — `scripts/score_tidmad_official_banded.py`:
per-band inference writes into **one** directory (`:584`), the band loop selects
checkpoints only (`:588-608`), and there is exactly **one** `score_vector` call
over the pooled directory (`:627-637`).

> **Its structural property is worth stating because Stage 3 must preserve it:
> zero band scalars are ever computed, so none can be averaged.** The script is
> not merely careful — it is built so that the forbidden operation has no
> operand. That is the standard for rows 60/61.

### 7.3 Where the pipeline currently departs from §7.2

| # | departure | §6 |
|---|---|---|
| `F-SCAND-1` | `prediction.py:269` computes an arithmetic mean over per-file **log** scores, and three production prompt sites advertise the grammar (`evidence_rendering.py:390`,`:509`; `proposal.py:61-62`) with no constraint on `N:M` | RELEASE BLOCKER |
| row 60/61 | Composed Best and Strict Best are **not implemented** | RELEASE BLOCKER |
| row 27 | no champion re-evaluation at full scope exists — **the headline number cannot currently be produced** | RELEASE BLOCKER |

**`F-SCAND-1` has never fired in a real run.** A complete census of 1,819
persisted records found **51 prediction metrics and zero** using the
`file_vector` grammar. No historical number needs correcting.

> **But it is latent because the grammar is too obscure for the model to use —
> not because the model avoided it.** Four persisted predictions ask for the
> aggregation in prose: *"averaged over validation files [15,16,17,18,19]"*,
> *"mean denoising_score over files [15,16,17,18,19]"*. **The model wanted the
> forbidden construction and was saved by bad ergonomics.** Removing the prompt
> examples alone would make the grammar *more* obscure — protection by
> obscurity, not a repair. The evaluator must **refuse**.

### 7.4 A second, larger measurement problem: 43 % of predictions never parse

`prediction.py:242-245` matches the bound id and legacy aliases by **exact
equality**. Of the 51 persisted prediction metrics, **29 parse and 22 do not** —
every free-text form resolves to `unrecognized` → `None` → the `unevaluated`
pool.

**So `scientific_accuracy` — the track record rendered to the proposer — is
computed over a filtered subset, and the filtering is invisible.**

> **This bears directly on arm comparability.** Parse failure is driven by prose
> elaboration, and Gold's advice instructs the agent to make full use of its
> budgets and explore broadly. **If Gold's predictions are more elaborate,
> Gold's parse rate is lower, and the two arms' track records are computed over
> differently-filtered subsets.** No arm effect has been measured — but the
> variation in prose elaboration is *observed*, not assumed, so this is a
> mechanism with a foothold rather than a hypothetical.

### 7.5 Validity: HealthGates

Gates fire at tuner round boundaries, never inside `score_vector`. Severity
resolution: `SKIP_ITER > SKIP_TO_FORMAL > INVALIDATE_ROUND > CONTINUE`.

**Two departures:**

- **`all_pass` vs shipped `any_pass` (row 54).** ~~All three TIDMAD blocking
  gates resolve to `any_pass` from **one** framework value
  (`configs/health_checks.yaml:37`). It is **not task-declarable at all** —
  `aggregation` is in `FRAMEWORK_OWNED_PARAMETER_KEYS` and a roster entry
  writing it is **rejected with `ValueError`**. One gate cannot be made strict
  without making all three strict.~~ **Both halves are now closed, and they
  were two separate things.** The VALUE flipped to `all_pass` in `f8ef0276`
  (#335). The DECLARABILITY closed under `F-SCAND-2`: `aggregation` moved out
  of `FRAMEWORK_OWNED_PARAMETER_KEYS` into `TASK_DECLARABLE_POLICY_KEYS`, so a
  roster entry declares it per gate and keeps its value while the framework
  value remains the default for entries that stay silent — which is every gate
  the shipped TIDMAD roster declares, so the campaign's `all_pass` is
  unmoved. The task config's own deferral
  (`configs/task_health/tidmad.yaml:73-76`) is discharged.
- **Gates are nested inside one of three scoring routes (`F-SCAND-3`).**
  `execution.py` has exactly two top-level scoring branches, `:1105`
  `ANCHOR_NORMALIZED` and the `else` at `:1320`; the gate block is `:1237`,
  **inside the first**. With `--no-is_trial` the whole chain runs **ungated,
  silently**. Latent today — no chain script passes it — **but Stage 2's
  frozen-winner retraining is exactly the invocation shape that would.**

### 7.6 Selection: which pool ranks

**`best_valid_formal_*` is the chain incumbent** and correctly rejects trial
sources (`core/resume.py:741`). **`best_denoising_score` and
`best_valid_denoising_score` mix trial and formal** (`policy.py:641-655`, no
`is_trial` filter), and the mixed pool drives the interpreter's headline "best
model" (`ordering.py:140-159`), the proposer's *"Overall raw best"*
(`evidence_rendering.py:46`,`:256`), prediction verification
(`prediction.py:92`), and — least obviously — **knowledge-cache eviction**
(`model_exploration.py:892-906`), where a model kept alive by a trial score can
evict one with a better formal score.

**Champion selection must key on `best_valid_formal_denoising_score`.** Row 59.

### 7.7 The FCNet reference — one question, not two

Two full-scope FCNet references exist and **disagree by 0.583**, which is 29 %
of the `+2.0` stopping threshold:

| | score | inference recipe |
|---|---|---|
| `siderius_score_split_official.json` (2026-07-20) | `5.851465049536501` | **not recorded** |
| `tidmad_official_fcnet_banded_score.json` (2026-08-01) | `6.434693649697849` | recorded and run |

**Verified identical between them:** checkpoint topology (both band-split over
the same four `.pth`), `s_max`, anchor map (both sha `0c44b608…`), `data_dir`,
file count, and coverage — the anchor map itself declares `segments_per_file:
200`, so 200 *is* full scope.

**Every element of the scoring layer matches. The difference is in the inference
decode.** The 2026-08-01 reference comes from a committed script documenting its
fcnet decode line-by-line against the paper — *".float() input (raw 0-255, no
normalization), float output cast `np.int8(output - 128)`"*. The other records
no decode at all.

> **A wrong decode does not raise.** Rounding instead of C-style truncation, or
> a missed `-128`, still yields a well-formed `int8` array that scores cleanly.
> **You get a plausible number, not an error** — the same silent-and-well-formed
> failure class as a threshold comparing incomparable units.

**The operator ask is one packet, not two** (`Q-FCNET-REF-1` + `D-BUD-17`):
**which reference, produced by which inference recipe, at which scope, compared
per-band or full-scope.**

---

## §7A DECISION PACKET — the FCNet reference and the "+2" rule

**One ruling, four scattered questions retired. Everything below is verified;
nothing is inferred.**

### The decision

> **Which FCNet reference does the campaign adopt, produced by which inference
> recipe, at which scope — and is "+2" measured per-band or full-scope?**

### What is already settled, so it need not be re-litigated

| | |
|---|---|
| **the ruler** | one anchor map, sha `0c44b6084dc8afc4dc2fa34f5253bc8d780b4e8ae086945e7051d8bf7928ba90`, `s_max = 295715680.14248306` — **byte-identical** between the repository's frozen `reference_data/segment_anchors.json` and the copy both references actually used |
| **the data** | **all twenty** `abra_validation_0000..0019.h5` byte-match between `/home/klz/Data/TIDMAD` and the canonical testpod set, verified against the Q3 manifest. `D-DATA-1`'s *"NOT byte-identical"* describes the **set** (423 vs 40 — a superset), not these files |
| **the scope** | the anchor map itself declares `segments_per_file: 200`, so **200 is full scope** and the two references do not differ in coverage |
| **the topology** | both references use the **same** band-split checkpoints — `FCNet_0_4` / `FCNet_4_10` / `FCNet_10_15` / `FCNet_15_20`, same file→checkpoint routing across all twenty |
| **the arithmetic** | no averaging shortcut exists. The scalar is a **ratio of sums**, and neither record carries a per-band numerator or denominator, so four band numbers require four real `score_vector` calls |

### The one thing that differs

| reference | score | inference decode |
|---|---|---|
| `siderius_score_split_official.json` (2026-07-20) | `5.851465049536501` | **not recorded** — it scores pre-existing deliverables and no inference provenance exists in the `fcnet/` tree |
| `tidmad_official_fcnet_banded_score.json` (2026-08-01) | `6.434693649697849` | **recorded and executed** — `seg_size 40000`, `batch_size 25`, per-file timings, `full_scope: True`; produced by `scripts/score_tidmad_official_banded.py`, whose fcnet decode is documented line-by-line against the paper (`:34-35`, `:465-472`): *".float() input (raw 0-255, no normalization), float output cast `np.int8(output - 128)` — the paper's exact C-style truncation"* |

**Gap: `0.583` — 29 % of the `+2.0` threshold.** Not noise.

> **Why the difference is invisible rather than loud.** A subtly wrong decode —
> rounding instead of C-style truncation, or a missed `-128` — still produces a
> well-formed `int8` array that scores cleanly. **You get a plausible number,
> not an error.** This is the same failure family as a threshold comparing
> incomparable units, and as a provenance field that echoes the request instead
> of the response: **wrong, well-formed, silent.**

**This lane states provenance, not correctness.** One candidate is reproducible
from a committed, reviewable script with a documented decode; the other has no
recorded recipe. Which is scientifically right is the operator's call.

### The second half: what "+2" is measured against

`D-BUD-17` authorises a success-based band-local early stop against an
`FCNet + 2` target. **Two readings remain open and they are different rules:**

- **per-band reference** — the only comparable form for a **band-local** stop;
  requires the four numbers `A2-FCNET` would produce;
- **full-scope reference** applied to the composed-best result (`D-BEST-1`) —
  which makes it a **campaign-terminal** stop, not a band-local one.

These have different stopping behaviour and the choice is not assumed here.

### Operational line item, not a decision

If the answer requires the four per-band numbers, `A2-FCNET` now needs **no
inference at all** — `score_vector` per band against the preserved deliverables,
minutes of CPU rather than a GPU run. **It still awaits the operator's word to
launch**, but the ask is now a scoring job. Whether it runs 5090-local or on
testpod is an operations choice either way.

---

## §5 THE AGENT'S ACTION SPACE

**What the agent chooses, what is fixed for it, and where the two currently
disagree.** §5.10's fairness principle depends on this being identical between
arms — *"the same experiment-fixed authorities and the same allowed agent action
space."*

### 5.1 What the agent genuinely controls

| | |
|---|---|
| **model architecture** | the entire point — proposed, implemented, validated, tuned |
| **loss function** | including agent-authored loss plugins |
| **hyperparameters** | within schema bounds |
| **the research narrative** | hypothesis, conclusion, discovery, key factor |
| **falsifiable predictions** | metric, current value, predicted value, rationale |

### 5.2 What is fixed for it — and what is only *supposed* to be

| parameter | intended | effective today |
|---|---|---|
| data portions | `EXPERIMENT_FIXED` | **`AGENT_CONTROLLED` by omission** — `F-LAUNCH-1` |
| `max_epochs` | trial 2 / formal 1 | one mode-agnostic knob; launcher passes 1 |
| `lr` when omitted | `5e-4` (paper spec) | **`1e-4`** — `F-SCANA-1`, a 5× silent departure |
| iteration horizon | 20 | launcher passes 10 |
| scoring metric | frozen | frozen ✓ |
| health thresholds | task-declared | task-declared ✓ — `aggregation` declarable per gate since `F-SCAND-2`; framework value is the default |

> **The `lr` row is the one to dwell on.** `TrainConfig` is the Pydantic gate
> that exists so raw LLM output cannot reach execution unvalidated. It validates
> the plan and then **substitutes a value five times smaller than paper spec**
> for any omitted key. The gate does its declared job and produces a
> scientifically wrong configuration doing it.

### 5.3 Two fields the agent may author and is never told about

`ExperimentPlan.order_strategy` and `file_order` are declared with full
validation (`hyperparam_tuning.py:1132-1173`), and **no prompt anywhere mentions
them** — zero hits across `agent/prompts.py`, `agent/prompt_templates/`,
`agent/llm_bridge.py`. Across 113 real records, `proposed_order_strategy` and
`proposed_file_order` are **null in every one**.

**Not a defect — a capability that does not exist in practice.** Recorded so
nobody reads the schema and concludes the agent declined to use them.

### 5.4 Scale guidance is advisory, and its reasoning is load-bearing

`D-TREAT-PARAM-1`: the **10M–500M** range is a **soft exploratory range**.
Parameter count is **never** a target, a quality objective, or a proxy for
compute or memory. Smaller is fully acceptable; above 500M is not prohibited
where practical.

> **The reasoning travels with the rule because it is what makes the rule
> followable: a high-parameter FC/MLP can be cheaper than a lower-parameter
> attention model.** An agent told only *"10M–500M, soft"* reads it as a range
> to fill. Told *why*, it can apply it. Practical scale is governed by the
> 60 GiB ceiling, the time ceilings, architecture throughput and
> validation/inference cost — never by parameter count alone.

---

## §8 FAILURE, RETRY, RESUME AND TRANSACTIONAL SUCCESS

**The frozen rule (`D-FAIL-1/5/8`): an infrastructure failure consumes no
scientific budget, and exit 0 is not success.** Both are currently violated.

### 8.1 Exit 0 is not success — and today it is

```text
_chain_common.sh:894-899   tests ONLY "status -ge 128"   (signal termination)
_chain_common.sh:901       return 0                       (unconditional)
run_one_iteration.py:2913  sys.exit(0) on no_records
v19_queue_runner.sh:904    advances the wave only on EXIT=0 — which is pinned
```

**This happened.** v20 attempt 1: both chains recorded `no_records` for **every**
iteration; the queue runner never noticed; the operator wrote `STOP` by hand.

> **It is not one defect — it disables two other guards.** The healthgate
> declaration refusal exits **2**; the chain-level fail brake exits **3**. Both
> swallowed by the same line. So the mechanism that would have caught v19's
> observe-mode repeat currently cannot stop anything. **A guard whose refusal is
> discarded is not a guard.**

**The repair is authored and unmerged** (`090e601b`, `99d05627`).

### 8.2 An infrastructure failure spends a scientific attempt

The correct vocabulary **exists and is well-designed** —
`INFRASTRUCTURE_FAILURE_STATUS` (`records.py:313`) with a reason map
(`:321-325`). **Its only callers are the resource-admission path.** A grep of
`records.py` for `LLMError`, `llm_error`, `APIError` or `provider` returns
**zero**. `ml_hyperparameter_tune_agent.py:1672-1673` marks **every** unhandled
exception `counts_toward_attempt_budget: True`.

**Historically:** 15 retries burning a round's budget in attempt 2; **91
`APITimeoutError` retries** in attempt 3.

### 8.3 A correct refusal crashes the round

`execution.py:404-405` does `resource_check.get("memory_killer") or {}` then
`.get(...)`. The producer's type is `dict | str | None`, and **`str` is
deliberate** — `isolated_probe.py:334-341`:

> *"`str` is a real member of each union, not sloppiness: when a field will not
> fit the 8 KiB budget the worker replaces it with `"[dropped: exceeded the
> rich-field budget]"` **so its absence is explicit rather than silent**."*

A truthy `str` survives `or {}` and raises. **Happened twice**, both times on a
**correct** VRAM refusal.

> **A mechanism built so that truncation would be explicit rather than silent
> crashes the consumer that was supposed to read it — and it fires when the
> system is at its most right.** Under a 4-way H100 posture where large
> candidates are *expected* to be refused, this is not a rare path.

### 8.4 Resume

- **`formal_eval_portion` is not a `RunInvariants` field at all** — neither
  `_CANONICAL` nor `_PROVENANCE`, which are required to partition every declared
  field. Two iterations at different formal eval scopes fold into one incumbent
  **with no refusal**. Recorded at `per_file_best.py:82`; **recorded is not
  enforced.**
- **`START_ITER` is captured from a stdout carrying 12,960 bytes of
  plugin-loader chatter** (`run_chain.sh:376`), with no numeric validation
  anywhere. Benign at iteration 1; **broken once the chain has generated
  models — exactly when resume matters.** Workaround: `--start_iter N`.
- **The fail brake does not survive a resume** — `consecutive_fails = 0`
  unconditionally, and `_resume_progress` returns only completed rounds and
  total attempts. With `--auto_resume` on by default, each relaunch gets a fresh
  budget of three fail-rounds.

### 8.5 What "completed" currently means

An iteration with **zero formal records** is stamped `completed` with a
**trial** `best_score` (`run_one_iteration.py:612-618`, reading the mixed pool).
All ten v20 attempt-3 manifests show exactly this: `best_valid_formal_score:
null`, `best_score` between 0.479 and 10.708, every one a trial score.

> **Stated precisely, because the larger claim would be false: decisions are
> honest.** The incumbent (`resume.py:269`) and the target stop
> (`model_exploration.py:3410`) both read the formal-only fields. **This is a
> reporting and operator-visibility defect, not a selection defect.**

### 8.6 The evidence rule this section earns

v20's own monitors reported `healthgate_invalidate: 0` for a run with **13
invalidations**, `type_errors: 0` for a run with an `AttributeError`, and a live
queue for a dead one — because `audit_snapshot.py:56-62` greps **log text** for a
string persisted only in **JSON**, greps `TypeError` when the crash was an
`AttributeError`, and checks an **attempt-2 screen name**.

> **A monitor reporting zero is indistinguishable from a healthy system.
> "The monitors were clean" is never evidence on its own.**

---

## §10 TREATMENT ISOLATION — what is verified, and what the gate cannot see

**The whole experiment rests on this section.** If the arms differ in anything
but the treatment, the campaign measures something other than what it claims.

### 10.1 The two gates, and why neither is sufficient alone

| gate | asks |
|---|---|
| **§5.8 Gold positive witness** | did the advice provably **reach** the proposer? |
| **§5.7 Blind negative witness** | did **no** advice reach it, by any route? |

> **A negative audit alone cannot distinguish "the treatment was withheld" from
> "the treatment was never delivered to either arm."** The positive witness is
> not bureaucracy — it is the only thing that proves the delivery mechanism
> works. **`T-IMPL-1` is exactly that failure**: the launcher hard-refuses
> `--advice` in **both** arms (`launch_prior_baseline_experiment.sh:142-146`).
> It was found by reading the launcher, not by running it — a Blind-only audit
> would have passed.

### 10.2 What the symmetry gate actually compares

`campaign_preflight.sh` compares **two hypothetical command lines on one
machine.**

**Outside what it can see:** home-directory stores · environment variables ·
**rendered prompt bytes** · machine-local calibration overlays · the generated
capability store.

> **It must compare rendered prompt bytes, not argv.** Every route that can
> actually differ between two pods produces identical argv and different
> prompts. **A PASS from this gate is much weaker evidence than its name
> suggests**, and §10 may not claim symmetry was verified until it compares what
> the models actually read.

### 10.3 Three unpinned routes by which the arms could differ

| route | status |
|---|---|
| `configs/task_config.yaml` | reaches **four** prompt surfaces; `run_invariants.py` contains **zero** occurrences of it. The lock pins the health and lit-review shas and not this one. Its snapshot is **first-writer-wins**, so from iteration 2 an edit reaches the LLM but not the record |
| `reference_data/root_papers_cache/` | the lit-review **config** sha is pinned; the paper **content** is gitignored and admitted regardless. Two pods, different caches, different literature, both "reproducible" |
| `agent_generated/` + `~/.siderius/generated_library/` | **117 plugins and 144 index rows today**, descriptions carrying *"keeps the validated WaveNet computation"* into both arms' prompts, unsuppressed by `baseline_isolation` |

**The third has a timing property that makes it worse than the other two.**
Preflight R8 checks the **checkout** store — correct today, and it would **FAIL
today**, which is the guard working. But the generated-library root is created on
the **first promotion**, after which writes go elsewhere and R8's globs go
vacuous.

> **The blind spot opens during the campaign's own first successful implementor
> round — after preflight has already reported PASS.** A check that is correct
> at launch and vacuous by iteration 2 is worse than one that never existed,
> because its PASS is on the record.

### 10.4 What "Blind" may honestly be called

**Blind is free of the two advice artifacts. Blind is not free of
framework-supplied TIDMAD knowledge.** Both sentences must be said, and the
paper must say the first rather than the second.

Two verified reasons:

- **`check_config_format_skill/wrapper.py:20-30`** injects TIDMAD architecture
  facts — *"punet and transformer are CLASSIFIERS (256 classes)"*,
  `segmentation_size 20000`, `batch_size limit 128` — into **every** planner
  prompt, with **no** composition gate. Both arms receive it, so symmetry holds;
  it is not an asymmetry, it is a **floor**.
- **`Q-ISO-1` cannot reach it.** Whatever `baseline_isolation` buys, it is not
  "no TIDMAD priors" — isolation cannot suppress a prompt the framework injects
  unconditionally.

**One claim explicitly retracted here**, because the corrected version is what
belongs in a paper: `raw_baseline` and `ground_truth` reach both arms and are
**not** a treatment leak. They are the metric's **floor and ceiling** —
instrumentation needed to interpret any score. §5.3's artifact is a prior
*model's* result. **Neither arm learns anything about a prior model from a floor
and a ceiling.** What the columns *do* narrow is Gold's marginal information:
from *"here is the scale"* to *"here is where a prior model sat on it"* — still
substantial.

### 10.5 Evidence that a control held under pressure

Recorded because §10 must argue that controls held, and **the credible version
of that argument comes from a case where holding cost something.**

On 2026-08-26 the coordinating session offered to pre-authorize a bounded
compute run under a delegation this lane could not verify, and to write the
grant if the launch-approval hook fired. This lane declined and surfaced it. **The
coordinator then ruled the decline correct — by a rule it had already applied to
a different lane that morning**, and withdrew the clause.

> **A control that binds only subordinates is a hierarchy. A control that binds
> the coordinator when the coordinator is the one asking is a control.** Two
> lanes refused a peer-asserted authorization the same day, both correctly.
> **That is stronger evidence than a test, because a test cannot be tempted.**

---

## §12 KNOWN LIMITATIONS AND SCIENTIFIC-VALIDITY RISKS

**This section's *unresolved* category must be EMPTY at launch.** An unresolved
confound that nobody re-reads before launch is accepted in practice whatever the
document says.

### 12.1 Currently unresolved — must be dispositioned

| id | risk |
|---|---|
| **`F-CONFOUND-2`** | shared host with time-varying neighbour load (~23–30 %) + fixed wall-clock ceilings + `D-FAIL-4` classifying breaches as SCIENTIFIC ⇒ **host load affects which Gold candidates survive.** Pending `A-HOST-1`. **Must resolve to *accepted non-blocking* or *resolved* — it may not drift into "accepted" by default** |

### 12.2 Accepted limitations — stated, not repaired

- **Blind is not information-free** (§10.4). The framework supplies a TIDMAD
  floor to both arms.
- **Formal-round training diagnosis is a single number.** At `max_epochs = 1`,
  `_trend` returns `single_point` and `validation_degraded_after_best` **cannot
  be True** (`training_diagnosis.py:55-57`). Only `train_validation_gap_final`
  carries information. **The agent receives a field named as an overfitting
  signal that is structurally incapable of reporting overfitting** — operator
  disposition required (`F-SCANE-2`).
- **`AGENT_CONTROLLED` differences are outcomes, not asymmetries** (§5.10).

### 12.3 An arm-asymmetry mechanism with a foothold — not a measurement

**43 % of prediction metrics never parse.** `prediction.py:242-245` matches by
**exact equality**; of 51 persisted prediction metrics, 29 parse and **22 do
not**, landing silently in the `unevaluated` pool. So `scientific_accuracy` — the
track record rendered to the proposer — is computed over a filtered subset.

> **Parse failure is driven by prose elaboration, and Gold's advice instructs the
> agent to make full use of its budgets and explore broadly.** If Gold's
> predictions are more elaborate, **Gold's parse rate is lower, and the two arms'
> track records are computed over differently-filtered subsets.**
>
> **No arm effect has been measured.** What is *observed* is the variation in
> prose elaboration — four persisted predictions ask for a band-scoped mean in
> words. That makes this a mechanism with evidence, not a hypothetical, and it
> is the reason it is in §12 rather than a footnote.

### 12.4 What is NOT a limitation, recorded to prevent re-discovery

- **No forbidden aggregation exists in the reporting path** (`F-AGG-CLEAR-1`).
  Two classes closed **structurally** — pandas is never imported; `np.average`
  never appears — so no pattern refinement could change the answer. A `per_band`
  search of `reports/` returns 613 hits; **all are `per_band_output_scaling` and
  siblings, referring to the 256 ADC output classes**, a different meaning of
  "band" entirely. `band_score` / `band_mean` / `cross_band`: zero repo-wide.
- **The FCNet reference and the campaign share a ruler.** The anchor map is
  byte-identical (`0c44b608…`) and all twenty validation files byte-match the
  canonical set.

### 12.5 How this section's confidence should be read

**28 release blockers were verified by a lane that was wrong three times in one
day and caught each.** Once by reasoning from a name instead of governing text;
once by letting an unverified clause ride inside a verified finding; once by a
correction that re-asserted exhaustiveness and lost an entry.

> **That is a weaker claim than "28 verified" and a more useful one.** The
> stated method — independent re-verification before routing, claim-type
> declaration, and printed commands behind any exhaustiveness claim — is what
> made those errors cheap. **A reader should calibrate the 28 against that
> record rather than trusting them uniformly.**

---

## §§9, 11, 13 — TO FOLLOW

| § | content | status |
|---|---|---|
| §9 | randomness and reproducibility | **blocked** — seed literals unchosen (§6.3) |
| §11 | hardware, runtime and admission | **blocked** — post-tag qualification (§6.2) |
| §13 | the launch checklist | last; assembled from §§6, 10, 12 |

Planned structure, so that the gaps are visible rather than implicit:

| § | content | status |
|---|---|---|
| §5 | agent action space — what the LLM controls and what it may never touch | to follow |
| §7 | scoring, validity and final selection | to follow — **depends on Scan D** |
| §8 | failure, retry, resume and transactional success | to follow |
| §9 | randomness and reproducibility | **blocked** — seed literals unchosen (§6.3 row 77) |
| §10 | treatment isolation: the Gold positive and Blind negative witnesses | to follow |
| §11 | hardware, runtime and admission | **blocked** — post-tag qualification (§6.2) |
| §12 | known limitations and scientific-validity risks | to follow — see below |
| §13 | the launch checklist | last; assembled from §§6, 10, 12 |

**§12's *unresolved scientific-validity* category must be EMPTY at launch.**
`F-CONFOUND-2` is the item requiring deliberate resolution into *accepted
non-blocking limitation* or *resolved*, and **it is currently in neither**. It
is recorded here so it cannot drift into "accepted" by default — an unresolved
confound that nobody re-reads before launch is accepted in practice whatever the
document says.

**§9 and §11 are marked blocked rather than pending.** The distinction matters:
pending work has an owner and a path; blocked work is waiting on something named
(seed literals from me, qualification from the Supervisor).

Released for cross-check as they stabilise. §12's *unresolved
scientific-validity* category must be **EMPTY** at launch; `F-CONFOUND-2` is the
item requiring deliberate resolution into *accepted non-blocking limitation* or
*resolved*, and it is not yet in either.
