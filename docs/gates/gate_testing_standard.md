# SIDERIUS Gate Testing Standard

**Status**: Canonical (2026-06-19)  
**Source**: Extracted from `enable_global_task_config` Checkpoint T lesson learned.  
**Purpose**: Reusable gate definitions for all SIDERIUS feature design docs.

---

## Real-LLM Gate config — BINDING POLICY

```text
Previous:
  real-LLM Gate config = openai_tiered_v1.json

Operator decision:
  real-LLM Gate config = openai_tiered_pro.json

Date:
  2026-08-13

Reason:
  Gate validation should exercise the production-capable model tier;
  repeated v1 runs were dominated by proposer/planner quality failures
  unrelated to the Step under test.
```

**Applies to Gate 1 and Gate 2**, and to any future real-LLM gate, until
an explicit operator decision changes it. `certify_minimal.json` remains
unusable for real-LLM gates for the reason already documented below.

---

## Gate model size and proposer advice — BINDING POLICY

```text
Previous:
  --trial_vram_budget_gb 24 / --formal_vram_budget_gb 24
  no --advice required

Operator decision:
  Gate 1 and Gate 2 limit each model to 4 GiB of GPU VRAM,
  AND pass a gate advice file stating that limit.

Date:
  2026-08-16

Reason:
  A Gate proves the plumbing still runs; it does not propose good models.
  Told nothing, the proposer optimises for science and gets refused at the
  structural pre-flight, which burns Gate attempts on the one outcome that
  exercises none of the code under test.
```

Both halves are required, and neither works alone:

| half | mechanism | what it does |
|---|---|---|
| enforcement | `--trial_vram_budget_gb 4 --formal_vram_budget_gb 4` | the pre-flight refuses anything larger |
| intent | `--advice advice/gate/<file>.json` | the proposer is TOLD the limit, in its own terms, and can aim at it |

Enforcement without intent is what produces refusals; intent without
enforcement is a suggestion.

This TIGHTENS the 24/24 in the parameter plans below, and it is not in tension
with "be generous on GPU VRAM": generous was always relative to a production
campaign. A wiring test wants the smallest model that honestly runs, not the
largest that fits.

**Evidence.** Step 07 PR 07b's post-refactor Gate 1 was launched without
`--advice`. Its second iteration burned two attempts on a 24-block dilated TCN:

```text
Loop Error: worker tree reached 25.183 GiB against a 24.0 GiB allowance
Loop Error: worker tree reached 24.881 GiB against a 24.0 GiB allowance
```

That was a POSTURE defect, not candidate bad luck — `advice/gate/` already
existed and already said the right thing. See
`docs/design/generic_framework_upgrade/step_07_tuner_policy_and_training_diagnostics/pr_07b_tuner_policy.md`
§14.11, and `advice/README.md` for the `advice/gate/` contract.

**Applies to Gate 1 and Gate 2**, and to any future real-LLM gate, until an
explicit operator decision changes it.

### If a Gate omits `--runtime_watchdog`, it must also omit `--validation_max_phase_seconds`

They are one fuse, not two flags. `HyperparamTuningInput` refuses the
combination at startup, before any spend:

```text
validation_max_phase_seconds requires runtime_watchdog_enabled=True:
the watchdog is what enforces the deadline, so without it the ceiling
would be recorded and never applied.
```

(`agent/schemas/hyperparam_tuning.py::_validate_validation_wall_clock` — "a hard
bound nothing enforces is worse than no bound".)

Dropping the fuse does NOT leave validation unbounded: `--validation_max_portion`
and `--validation_max_train_samples` size the work and have no watchdog
dependency — the latter is this standard's stated **primary sizing mechanism**.
This is the only interlock of its kind; audited 2026-08-16.

This policy changes ONLY which LLM config a real-LLM gate uses. Gate tier
definitions, the assignment-by-commit-type rules, pseudo-vs-real
definitions and every runtime bound are unchanged. A separate
Gate-efficiency audit (iteration/round counts, hard wall-clock and
max-step bounds, per-PR temporal depth) is DEFERRED and is not part of
this correction.

---

## Gate definitions

Every SIDERIUS feature commit plan uses one or more of these gates before
committing and before merging. The gate tier is declared in each commit's
"Test gate" annotation.

### Unit only (no gate label)

Pure Python, no LLM, no GPU. Run freely without user approval.

- `pytest tests/unit/...`
- ruff check + ruff format --check
- pyright

### Gate 1 — Real LLM + pseudo training

**Purpose**: verify that a real LLM, given the new/changed prompts, produces
structurally valid output (compiles, passes schema validation, passes
dummy-tensor check). Does NOT require real training.

**When to use**: after any commit that changes an LLM-facing system prompt or
schema (implementor, proposer, validator, interpreter).

**Setup**:
- Real LLM: `llm_configs/openai_tiered_pro.json` (gpt-5.5 across every
  role) — see the real-LLM Gate config policy above
- Pseudo training: dummy-tensor check only — no GPU, no real training loop
- Estimated wall time: ~2-5 min
- Estimated cost: ~$0.05-0.20

**Pass criteria**:
- LLM call completes without error
- Output passes Pydantic schema validation
- Generated code (if implementor) compiles + passes dummy-tensor check

**Needs user approval**: yes (real LLM cost).

---

### Gate 2 — Real LLM + real training (smoke test)

**Purpose**: verify that the REAL path executes end to end — real LLM,
real candidate, real training, real inference, real scoring, a finite
result. It is functional validation, **not** a miniature scientific
campaign, and not an assessment of model quality.

**When to use**: at Checkpoint commits (end of a feature's commit plan)
before merging to master.

#### The governing principle

```text
the Gate harness owns    the amount of REAL WORK a resolved plan may execute
it does NOT own          tuner policy, trial-vs-formal mode, optimization strategy
```

The planner plans normally and may elect trial or formal; the Gate bounds
what that election is allowed to cost. Everything below follows from that
split — including why there is no force-trial flag.

#### Canonical command (cold-start, bounded)

```bash
bash sdsc_submission_scripts/run_chain.sh \
    --mode lilab \
    --workspace /tmp/gate2_$(date +%s) \
    --run_name gate2_smoke \
    --num_iterations 1 \
    --max_rounds 1 \
    --max_proposal_attempts 3 \
    --max_epochs 1 \
    --data_scope 4-9 \
    --health_gate_files 4,5,6,7,8,9 \
    --validation_max_portion 0.01 \
    --validation_max_train_samples 2000 \
    --validation_max_phase_seconds 900 \
    --runtime_watchdog \
    --no-force_formal_round \
    --trial_vram_budget_gb 24 \
    --formal_vram_budget_gb 24 \
    --llm_config llm_configs/openai_tiered_pro.json
```

No `--seed_paths`: every real-training gate run is cold-start (see
"Partial-scope rules" below).

#### The dataset directory is resolved automatically — do not hardcode it

The canonical command deliberately does **not** pass `--data_dir`. The
launcher resolves the physical dataset directory at launch, from the
machine-local `tidmad_data_config.yaml` (`execute_tools.data_paths`), and
**validates it before any LLM or training work begins**. A machine-specific
absolute path must never appear in this standard, in the chain scripts or in
tests — only in that per-machine (gitignored) config.

```text
--data_dir <path>          operator override, highest precedence
omitted (the default)      tidmad_data_config.yaml answers
neither resolvable         LAUNCH REFUSED, exit 2, before any spend
```

Pass `--data_dir` only to point a run at a *different* copy of the data.

**Why this is stated here.** During Step-04a's Gate validation a run reached
the tuner with `data_dir=None`, and the pre-phase GPU measurement failed
closed — *after* a real LLM had generated, validated and registered a
candidate. The launcher performs the resolution now, so that failure mode
costs nothing instead of ~10 minutes of paid work. If a Gate refuses at
launch with `LAUNCH REFUSED: ... dataset directory ...`, fix the machine
config or pass `--data_dir`; do not work around it by editing this file.

**Important**: do NOT use `tee` to capture chain stdout. The Claude Code
harness capture file is sufficient and can be read on demand. `tee` writes
a duplicate log to `/tmp` that accumulates over the run and can exhaust
the tmpfs filesystem.

#### What each bound actually does

| Parameter | Role | Why it is what it is |
|---|---|---|
| `--validation_max_train_samples 2000` | **the Gate's primary sizing mechanism** | Absolute ceiling on the ML segments one training epoch may contain, applied where the epoch is BUILT — fewer segments are read and fewer optimizer steps exist before any of them run. It CLAMPS; it never rejects. With batch_size 1 (the worst the planner can choose) this is ≤ 2,000 steps. |
| `--validation_max_portion 0.01` | fractional envelope, both modes | Clamps the RESOLVED `trial/train/eval` portions after the planner, after `plan_overrides` and after the formal-round override chain. It governs formal too — that is what stops `formal_eval_portion`'s default of 1.0 pulling the whole scope into a smoke test. |
| `--max_epochs 1` | epoch ceiling | Clamps the planner's epochs. Multiplies with the sample ceiling to bound total steps. |
| `--data_scope 4-9` + `--health_gate_files 4,5,6,7,8,9` | file-count envelope | DS8-mandatory pairing (see below). Bounds inference and scoring, which are per-file. |
| `--validation_max_phase_seconds 900` + `--runtime_watchdog` | **emergency fuse only** | Absolute wall-clock ceiling per phase, enforced by the RT4 watchdog as an extra deadline candidate — never as an admission input, so it cannot skip the attempt. A normal Gate never reaches it. If it fires, classify that as runtime/harness abnormality, not as successful sizing: a run killed at the deadline yields no evidence and wastes the whole attempt. Requires the watchdog (the schema refuses the ceiling without it). The watchdog floor still applies — effective ceiling is `max(this, --runtime_watchdog_floor_seconds)`. |
| `--llm_config openai_tiered_pro.json` | **mandatory** (operator, 2026-08-13) | gpt-4o-mini (`certify_minimal.json`) cannot reliably produce proposals that pass the validator. **`openai_tiered_v1.json` is no longer sufficient either**: it puts `propose.comparison`, `validate` and `tune.reflector` on mini/nano tiers, and during Step 03 produced a proposer that invented a list-valued `dilation_cycle` against the tuner's scalar-only config contract (3 codegen attempts burned) and a planner that repeatedly chose `batch_size 1` with `portion 0.05`. Those are proposer/planner **judgment** failures: they burn Gate wall-time without exercising the plumbing the Gate exists to test. |
| `--num_iterations 1`, `--max_rounds 1` | minimum temporal depth | See "Temporal depth" below. |
| `--no-force_formal_round` | optional | Leaves the round mode to the planner. Safe to omit: the envelope binds formal exactly as it binds trial. It is **not** a force-trial flag — it only stops the HARNESS forcing the last round formal. |

#### What is NOT a bound

Three mechanisms look like limits and are not. Each cost a Gate attempt
during Step 03:

| Mechanism | What it really is | Failure it caused |
|---|---|---|
| `--trial_time_budget_minutes` | forecast-based **admission** input | one round ran **33m53s** under a "5 minute" budget — a bad forecast admits the attempt and the epoch then runs to completion |
| `--trial_portion` | a fraction, floored at 0.01 in schema, and **overridable by the planner** | the CLI said 0.01, the planner chose 0.05; and 1 % of the scope still resolved to 12,500 steps, because samples-per-PSD is `psd_segment_length // seg_size` and `seg_size` is the planner's model config |
| `--max_steps_per_attempt` | a **rejection** guard | set below the planner's normal solution, every round was SKIPPED — zero training, zero score, and the Gate proved nothing. Keep it at a level that catches pathological states; never use it as the sizing mechanism |

`--no-force_formal_round` belongs in the same family: it prevents the
harness forcing formal, not the planner electing it. During Step 03 the
planner elected formal anyway and resolved to 250,000 optimizer steps.

#### Temporal depth is failure-class driven

Default: **1 iteration × 1 round**, planner-controlled mode. Deeper only
when the change under test needs it:

| What the PR changes | Depth |
|---|---|
| ordinary execution / config / contract change | 1 iteration × 1 round |
| multi-round tuner policy | ≥ 2 rounds |
| cross-iteration behaviour or resume | ≥ 2 iterations |
| trial→formal promotion semantics | exercise promotion explicitly |

**The table gives FLOORS, and SEMANTIC LATENCY can raise them (binding,
operator decision 2026-08-21).** A depth is only adequate if the Gate's own
witness is OBSERVABLE at that depth. Trace where the witnessed value is
produced, persisted, restored and finally CONSUMED — count the boundaries,
do not assume the floor suffices:

```text
produced at iteration N
persisted after N
restored at N+1
consumed only at N+2
    -> 3 iterations are REQUIRED, not an expansion
```

This is not scope growth: it is what makes an already-required property
actually observable. Raising depth for **latency** is legitimate; raising
it to give a model more chances to succeed is the scope expansion the
section above forbids.

**Check the harness precondition too.** A deterministic test may satisfy
the witness only because its fixture SEEDS prior state that a real
cold-start Gate does not have (real-training Gates are cold-start by
mandatory rule — no `--seed_paths`). Where a Gate's witness depends on
prior-iteration state, confirm the real run can produce it at the chosen
depth; a seeded unit test proves nothing about a cold-start chain. Step 10
P5+P6 froze 2 iterations on exactly that mistaken premise and the
requirement was unsatisfiable — its witness needed 3.

This governs HOW a required Gate runs. It does not let a PR reason its
way out of a Gate the assignment table requires.

**Estimated wall time**: ~10-20 min, dominated by LLM latency (interp +
3-stage proposer + implementor + validator), with bounded training,
inference and scoring behind it. The pre-2026-08-13 shape was ~30-60+ min
and could exceed two hours when a formal round pulled full scope.

**Estimated cost**: ~$1-2 (gpt-5.5 dominant role).

#### PASS criteria — functional, not scientific

The real path must have executed:

1. Chain exits 0
2. A real candidate was generated, validated and registered
3. **Real training actually executed** (not pseudo, not skipped)
4. Real inference actually executed
5. Real scoring actually executed and produced a **finite, non-null** result
6. Every round has a recorded `gate_action` in `final_record`
   (any value: PASS, INVALIDATE_ROUND, ABORT_CHAIN)
7. A `None` / `-inf` score is acceptable ONLY with a corresponding
   `gate_action` of `INVALIDATE_ROUND` or `ABORT_CHAIN` in that round's
   record — a `None` score with no `gate_action` is a framework bug
8. No phantom `5.5762667` appears as a final accepted score
9. When the PR migrates a specific boundary, evidence that the boundary
   was exercised

Explicitly **NOT** pass/fail criteria:

- `denoising_score` > baseline, or above any threshold
- loss convergence, or incumbent improvement
- whether the model learned to denoise
- scientific model quality of a one-epoch, 1 %-scope, sample-capped model

A model may be collapsed or scientifically worthless while the functional
Gate correctly proves the real path executed. Only a PR that changes
those semantics may require them.

**Needs user approval**: yes (real LLM + real training cost and time).

#### Gate scope ownership — DO NOT BLINDLY EXPAND (binding, operator decision 2026-08-21)

The "PASS criteria — functional, not scientific" rule above is necessary
but was **not sufficient**, and a real run proved it. This subsection is
the part that was missing.

**The rule.** A Gate validates the real execution path owned by the
**changed failure class**. Encountering a subsystem during the run does
**not** enrol that subsystem's success into the acceptance contract.

Before adding ANY new Gate acceptance requirement, answer all five:

1. Is this property owned by the code changed in this PR?
2. Is failure of it evidence that the *changed feature* is broken?
3. Is it already owned by another unit / integration / Gate test?
4. Does adding it introduce model-quality or stochastic dependence?
5. Does it increase iterations, rounds, depth or workload beyond the
   smallest faithful proof?

If these do not justify expansion, **do not add the requirement**. A
neighbouring subsystem may be *observed and recorded* without becoming a
PASS condition.

**Test isolation when a neighbour BLOCKS the path.** The PASS criteria
above already permit a collapsed model and an `INVALIDATE_ROUND`. What
they did not cover — and what actually bit — is a PR whose own evidence
contract needs a **committed record**, while a quality subsystem
invalidates the round and prevents one. Then the Gate's outcome is decided
by whether a tiny model happened to train well, which is not the failure
class under test.

```text
subsystem A is under test
subsystem B can block A's path on a criterion unrelated to A's correctness
    -> isolate A from B, using an EXISTING production-supported control
    -> never by changing B's production semantics, thresholds or tests
```

This is test isolation, not weakening. B keeps its own evidence owners.

**Never tune the science to make an infrastructure Gate green.** Rerunning
a Gate with progressively more specific model/loss/epoch advice until a
random candidate clears an unrelated threshold turns the Gate into a
miniature tuning campaign and destroys its meaning. If a Gate's outcome
starts depending on LLM luck, fix the Gate *contract*, not the model. A
Gate failure caused solely by unrelated stochastic model quality is **not**
evidence that the feature under test is broken.

**Negative scientific evidence is still real evidence.** "The candidate
trained and scored, but produced low-diversity outputs" is a valid,
usable finding. Where a PR requires a "usable" artifact, usable means
*structurally valid, genuinely produced by the completed real run, and
substantive enough to exercise the boundary* — never *scientifically
good*.

**Where the line actually falls** (the distinction the rule must make):

| PR changes | model quality in scope? |
|---|---|
| lifecycle / persistence / restore / orchestration | **no** — poor score, collapse and negative findings are all acceptable |
| resume semantics | **no** — a correct restore with a poor benchmark score passes |
| metric ORDER / direction semantics | **no** — selection correctness is the failure class, not the score |
| HealthGate behaviour itself | **yes** — Health verdicts ARE the changed failure class |
| a training algorithm whose convergence IS the feature | **yes** — convergence is legitimately in scope |

**Per-PR Gate sections must state this explicitly** — see "Gate section
required fields" below.

#### Gate section required fields (every child design that specifies a Gate)

State these, so scope cannot expand silently later:

* **FAILURE CLASS UNDER TEST** — the exact changed real-system property.
* **REQUIRED REAL COMPONENTS** — only those needed to exercise it.
* **NON-REQUIRED SCIENTIFIC QUALITY** — name the neighbouring quality
  criteria that are explicitly NOT conditions, wherever ambiguity is
  possible (HealthGate PASS, convergence, score thresholds, collapse
  absence).
* **MAXIMUM TEMPORAL DEPTH** — default 1 iteration × 1 round; see
  "Temporal depth is failure-class driven".
* **EXTRA DEPTH JUSTIFICATION** — required before adding iterations/rounds.
* **ISOLATION** — any unrelated blocking subsystem disabled, and the
  existing production-supported control used to do it.

---

### Partial-scope rules (DS8-mandatory, all real-training gate runs)

Added 2026-07-27 after P1-V2 attempts 1 and 2 exposed two DS8
(`enable_partial_file_list`, PR #130) rules the pre-DS8 Gate standard
had not been updated for. When a real-training gate run uses a
partial `--data_scope` (anything narrower than the full 20 files),
**both** of the following are required — otherwise
`run_one_iteration.py` refuses to start at pre-flight:

1. **HealthGate monitored files must be paired with the scope.**
   Pass `--health_gate_files` with the EXACT resolved scope
   (e.g. `--data_scope 4-9 --health_gate_files 4,5,6,7,8,9`).
   DS8's `validate_health_scope` refuses to launch when the shipped
   `configs/health_checks.yaml`'s `peek_file_indices` fall outside
   the resolved scope OR when any check omits an explicit peek list
   under partial scope. The external task workflow must derive both arguments
   from one declared scope authority.

2. **Always cold-start real-training gate runs (operator rule,
   2026-07-27).** Omit `--seed_paths` entirely. Rationale:
     - **DS8 correctness**: the canonical seeds
       (`small_sample_trial_v0` wavenet + punet) are pre-DS8
       full-scope artifacts. DS8's `validate_stamped_invariants`
       (`core/run_invariants.py:321`) refuses to admit unstamped
       (= legacy full-scope) ingress evidence into a partial-scope
       run — surfaced by P1-V2 attempt 2 in under 2 s.
     - **Uniformity**: pre-DS8 seeds are stamped for a fixed scope
       different from most partial gate configurations. Rather than
       maintain per-scope seed inventories, PR #126
       (`nodes/result_interpretation_agent` `cold_start=True`
       deterministic path, no LLM call) lets every gate run start
       from a fresh workspace.
     - **Provenance**: cold-start makes gate evidence
       self-contained — everything in `$WS` was produced by that
       one gate invocation.
   Concretely: `--seed_paths` MUST NOT appear in any new real-
   training gate command. V18r's launcher already runs this way
   (`_chain_common.sh:280-283` documents cold-start as valid).
   Exception: reproducing a specific historical run whose exact
   seeded state matters — operator-approved on a case-by-case
   basis only.

   **Cold-start checklist (arXiv U3, #259).** "Cold start" is more than
   omitting `--seed_paths`: several caches survive a fresh workspace and
   silently carry evidence or capability state between runs. Work the
   list IN ORDER before any cold-start gate or experiment launch; the
   right-hand column says what a genuinely cold run looks like.

   | # | state | cold-start action |
   |---|---|---|
   | 1 | the chain workspace (`--workspace DIR`) | CLEAR — a fresh, empty (or absent) directory; a reused workspace resumes against its `run_invariants_lock.json` instead of starting cold |
   | 2 | `--seed_paths` | OMIT entirely (the operator rule above) |
   | 3 | `agent_generated/models/` + `agent_generated/_capability_index.json` | CLEAR for a cold CAPABILITY surface: the proposer advertises this registry (Branch B) and the plugin loader registers every `.py` here at import — leftover plugins from prior campaigns are prior evidence |
   | 4 | `${SIDERIUS_CHAIN_WORKSPACE}/plugins/` | cleared BY step 1 when the workspace is fresh; listed separately because `get_model_description` resolves plugin descriptions from here across iterations |
   | 5 | `reference_data/root_papers_cache/` | RETAIN by default — it caches per-paper EXTRACTS of the fixed root-paper set (deterministic inputs, not run evidence); clear only when the experiment's question includes the lit-review retrieval cost itself |
   | 6 | the runtime-calibration store (`$SIDERIUS_CALIBRATION_DIR`, default `~/.siderius/runtime_calibration/`) | RETAIN — host calibration, not task evidence (the lock RECORDS it and never compares it); clear only for a cold-HOST measurement study |
   | 7 | the advice file (`--advice` / `--human_advice_file`) | OMIT for a cold run; `launch_prior_baseline_experiment.sh` refuses advice files in BOTH arms because a V20 explorer file names FCNet's 323 M scale |

   The two-arm prior-art experiment launches through
   `sdsc_submission_scripts/launch_prior_baseline_experiment.sh`, which
   already refuses `--seed_paths` and advice files; items 1 and 3 remain
   the operator's manual pre-launch steps.

### Gate 2 parameter plans (Lite / Regular) — OPT-IN deeper shapes

**These are not the default.** The canonical bounded command above is.
Reach for a plan here only when the PR's failure class needs the extra
depth — a forced formal round (Lite) or a multi-iteration LLM loop
(Regular) — per "Temporal depth is failure-class driven".

Both plans carry the Gate envelope: add
`--validation_max_portion`, `--validation_max_train_samples` and the
`--validation_max_phase_seconds` + `--runtime_watchdog` fuse from the
canonical command. The envelope is what makes Lite's forced formal round
safe; without it, `formal_eval_portion`'s default of 1.0 and a
planner-chosen batch size are exactly how the 2h 02m round of
2026-06-22 happened.

Added 2026-07-23 from the runtime-control Gate 2 audit (design doc
§12, commit `cb1b6b0`). Two vetted combinations. Guiding policy:
**be generous on GPU VRAM, stingy on wall time** — a VRAM-gate
rejection wastes a whole Gate attempt. VRAM feasibility stays with the
production preflight and batch resolver; the Gate envelope sizes how
much work runs, not whether a step fits in memory.

**Both plans below assume the DS8 partial-scope rules above** — the
tables show only the deltas from those rules. Partial-scope plan
invocations always include `--health_gate_files <scope>` and always
omit `--seed_paths`.

**Portion semantics crib (code-traced — do not infer from names):**

- Training scope: per file `max(1, round(formal_portion × 200))` PSD;
  per-epoch subsample `max(1, round(formal_train_portion × scope))`;
  steps = `(ΣPSD × (10M//seg)) // batch × epochs`.
- **Eval scope is INDEPENDENT of `formal_portion`**: per file
  `max(1, round(formal_eval_portion × 200))` PSD — drives inference
  AND scoring. The naive `formal_portion × formal_eval_portion`
  intuition is wrong.
- Per-file floors of 1 PSD mean many-file scopes never go below
  1 PSD/file regardless of portion.
- Scoring = eval PSD × per-host `per_psd_segment_seconds` ÷ 8 workers
  — ≤ ~6% of total even at `formal_eval_portion=1.0` on a 6-file
  scope, so it stays a historical-estimate phase under the 0.10
  share limit.

| Parameter | **Lite Plan** (~30-45 min, ~$1) | **Regular Plan** (~45-90 min, ~$1.5-2.5) |
|---|---|---|
| Purpose | fastest full-lifecycle proof incl. ONE forced formal round | tighter runtime-prediction statistics + multi-iteration LLM loop |
| `--num_iterations` / `--start_iteration` | 1 | 2 |
| `--max_rounds` | 2 (1 trial + 1 forced formal) | 2 |
| `--max_proposal_attempts` | 3 | 3 |
| `--data_scope` | `4-9` (6 files) | `4-9` |
| `--health_gate_files` (DS8-mandatory, paired with `--data_scope`) | `4,5,6,7,8,9` (matches scope exactly) | `4,5,6,7,8,9` |
| Seeds | **NONE — cold-start** (see "Partial-scope rules" above) | **NONE — cold-start** |
| `--trial_portion / --train_portion / --eval_portion` | 0.02 / 1.0 / 0.01 | 0.02 / 1.0 / 0.01 |
| `--formal_portion / --formal_train_portion / --formal_eval_portion` | 0.02 / 1.0 / 0.01 (→ 3,000 steps @ seg 10k b8; 12 eval PSD) | 0.10 / 1.0 / 0.05 (→ 15,000 steps; 60 eval PSD) |
| `--max_epochs` | 1 | 1 |
| `--trial_time_budget_minutes` | 5 | 5 |
| `--formal_time_budget_minutes` | 30 (Gate-specific; production policy stays 120) | 45 |
| `--trial_vram_budget_gb / --formal_vram_budget_gb` | 24 / 24 (GENEROUS — never let the VRAM gate eat a Gate attempt) | 24 / 24 |
| `--runtime_watchdog` | on (passive validation) | on |
| Guardrails | defaults (150k / batch≥4) | defaults |
| force_formal_round | **default ON** (deviation from the trial-only smoke — required when the feature under test must exercise real formal admission; use `--no-force_formal_round` for features that don't) | default ON |
| `--llm_config` | `openai_tiered_pro.json` | `openai_tiered_pro.json` |

Notes:

- The trial-only smoke (canonical command above) remains correct for
  features that don't touch the formal path; the plans here add the
  formal-round variant with SMALL formal portions instead of the
  dangerous full-dataset formal that motivated
  `--no-force_formal_round`.
- Estimated single-formal-round compute at Lite scale: setup ~20 s +
  training 1-5 min (unknown LLM-invented model, 25-100 ms/step band)
  + inference ~10-25 s + scoring ~3 s + ~50 s subprocess startups.
- Pathological/rejection demonstrations should NOT run the workload:
  drive the supported executor API directly with no LLM, guardrails
  overridden, and the production budget — rejection should stop after setup
  and live verification rather than executing the full workload.

**Failure handling**:
- If all proposals fail validation → LLM quality issue, not a feature bug.
  Check that `--llm_config openai_tiered_pro.json` is set (not
  certify_minimal, and not the superseded `openai_tiered_v1.json`).
- If SIGSEGV / OOM during inference → retry once; if repeats, investigate
  VRAM budget. Check `--trial_vram_budget_gb` setting.
- If disk fills → `--trial_portion 0.02` + `--trial_time_budget_minutes 5`
  must both be set. Check `/tmp` usage with `du -sh /tmp/*`.

---

## Gate assignment by commit type

| Commit type | Typical gate |
|---|---|
| Config files, YAML, schema-only | Unit only |
| New loader/renderer (pure Python) | Unit only |
| Prompt placeholder substitution | Unit only + optional Gate 1 |
| New LLM-facing system prompt | Gate 1 |
| New agent node or workflow wiring | Gate 1 |
| Checkpoint (end of feature) | Gate 2 |
| Loss function generation (L4) | Gate 1 (dummy-tensor) + Gate 2 at Checkpoint L |

---

## Seed paths (historical reference — DO NOT USE for new tests)

> **Operator rule 2026-07-27**: all new real-training gate runs are
> cold-start — do NOT pass `--seed_paths`. See the "Partial-scope
> rules" section above for the DS8 rationale (these seeds are
> pre-DS8 full-scope artifacts and cannot be admitted into any
> partial-scope run). The paths below are kept only so historical
> gate logs remain interpretable.

```
/home/klz/Data/SIDEREIS_DATA/wavenet/small_sample_trial_v0/agent/run_output_small_sample_trial_v0_agent.json
/home/klz/Data/SIDEREIS_DATA/punet/small_sample_trial_v0/agent/run_output_small_sample_trial_v0_agent.json
```

Exception: reproducing a specific historical seeded run whose exact
state matters — operator-approved on a case-by-case basis only.
