# V18r campaign audit — 2026-07-25 (INTERIM)

**Status: INTERIM — the campaign did not finish.** The §15 standard
(`reports/v18_20260724.md` §15) specifies this artifact for execution
after all 8 exit markers + queue `ALL DONE`. It is executed early, at
operator request, as a diagnosis-run audit: the §13h cohort was
terminated externally (container replacement, §0.1) at iterations
6/7/4/4 of 20, and the audit findings below are actionable without
further campaign data. All ten §15 dimensions were executed against
the standard's stated sources, deliverables, and attention criteria.

- **Cohort audited**: §13h third restart ONLY — `v18r_loss_04_09`,
  `v18r_arch_04_09`, `v18r_loss_10_14`, `v18r_arch_10_14`, launched
  2026-07-24 07:57–07:59 UTC from the rolling 4-way topology (§13c),
  uniform protocol: trial SF 3.0 / formal SF 2.0 / legacy base 1.5
  (fallback only), watchdog floor 120 s, VRAM 16/16 GB, budgets
  20/120 min, refined v18r advice incl. full Phase-3
  capacity-fidelity layering from iteration 1. Single-protocol — no
  phase split (§13h), so the §15 ground-rule note about the SF-1.5
  `arch_04_09` asymmetry applies only to the ARCHIVED first launch,
  not to this cohort.
- **Data cut**: last chain log writes 2026-07-25 02:28–03:19 UTC.
  21 iterations started, 17 closed with `run_output` records, 4 in
  flight at termination (no manifest / run_output; contribute to log
  counts only).
- **Archive isolation**: `legacy_v18_*`, `legacy_v18r_undersized/`,
  `halted_v18r_loss_04_09_trialSF15/` were never read (directory
  names only). Verified zero references to any archive in all four
  chain logs and all live workspace JSON/JSONL/YAML (§9).
- **Scoring rules honoured**: no score aggregated or averaged across
  scopes anywhere in this report; all comparisons are per-band
  (`scoring-aggregation-standard`). Per-band official comparators are
  audit-DERIVED (§7.0) — the official pages publish full-scope
  headline numbers only.

## 0. Executive summary

### 0.1 Overriding event — the cohort was terminated externally

The RunPod container was replaced at **2026-07-25 04:14:47 UTC**
(hostname `94cdab4290e0` → `aefdc1fd84ec`; evidence: `ps -o lstart=
-p 1`, `iter_00*_hardware.json` hostnames, every observation record).
All four chains died mid-phase between 02:28 and 03:19 UTC — three
within 100 s of each other, a host-level freeze signature, not four
independent failures:

| Chain | Last log write | Died during |
|---|---|---|
| v18r_loss_04_09 | 03:17:31 | iter_006 round 1 training (`loss_aligned_wavenet_hardness_weighted_iter_006_003`) |
| v18r_arch_04_09 | 03:19:11 | iter_007 round 3 planning |
| v18r_loss_10_14 | 03:18:31 | iter_004 scoring |
| v18r_arch_10_14 | 02:28:13 | iter_004 inference (silent long phase) |

No exit markers exist or can exist (`/tmp` wiped); exit codes are
permanently unknown; ~5.6 h of in-flight work (4 partial iterations,
~1.84 M tokens) was lost. GPU is at baseline; no orphan processes.

**Restart blockers (must fix before any relaunch):**
1. **`screen` is absent from the new container image** (`tmux` is
   present). The §8 launchers and `v18r_queue_runner.sh` depend on it.
2. **Queue-runner state bug**: `v18r_queue_runner.sh` advances its
   state index even when `screen` fails ("advance even on guarded
   skip"), and two of its three duplicate guards depend on `screen`.
   Relaunched unfixed, it would burn all four queued chains
   (`15_19`/`00_03` pairs) as ERROR skips in ~4 loop iterations and
   log a false `ALL DONE`.

The queue runner never launched anything (4-way occupied all
`MAX_CONC=4` slots; `v18r_queue_state` never written) — the queue
order `15-19 loss → 15-19 arch → 0-3 loss → 0-3 arch` is fully
pending. The four live workspaces are intact; invariants locks
validate; resume per §12 (`V18_RESUME=1`, `--auto_resume`) is
possible once the blockers are fixed.

### 0.2 Verdict table

| § | Dimension | Verdict |
|---|---|---|
| 15.1 | Key-findings growth | ⚠️ NEEDS ATTENTION (early-warning, 04_09 pair): novelty front-loaded iters 1–3, canonical promotions ~0 since iter 4, spend flat-to-rising |
| 15.2 | Lit-review adoption | ✅ PASS (50 % of proposals adopt); 3 sub-flags: uninstrumented cost, single-paper monoculture, 32 % S2 failure |
| 15.3 | Failure taxonomy | ⚠️ TRIPPED: paid-failure wall 38.6–57.1 % (> ~25 %); `full_clone` freeze breaches the >3×-without-adaptation rule on 2 chains |
| 15.4 | Kill ledger | ⚠️ TRIPPED both criteria: 35/36 kills near-deadline; formal kills recurred at SF 2.0 — fixed-scalar SF is not converging. Watchdog mechanism itself: flawless |
| 15.5 | HealthGate | Decided: 04-09 = models genuinely collapsed (gates correct); 10-14 = 2 material false positives in an uncalibrated quadrant. `pearson_dispersion` is the standout V19 candidate |
| 15.6 | Prediction quality | ❌ CONTRACT BROKEN every predicted phase; admission precision 19 %; priors structurally reset per iteration; 2 admission/deadline code defects |
| 15.7 | Scores | ⚠️ PARTIAL: `arch_10_14` beats its band raw floor on VALID formals (1.3111); band 4-9 both chains below floor, zero valid rounds. Trial-vs-formal criterion clean |
| 15.8 | Cost | ❌ ESTIMATE BROKEN: 613.6 k tok/iter vs 160–400 k band; wasted wall 39.5–46.9 % (> ~30 %). Resource envelopes never touched |
| 15.9 | Provenance | ✅ CLEAN — no chain quarantined; 4 uniform gaps (launch commit, chain_id, watchdog_status, exit codes) |
| 15.10 | Delta gate | INERT: 0 skips / 0 bypasses in 17 iters; unreachable without HealthGate-valid trials. Incumbent counterfactual: 1 firing, 586 min saved |

### 0.3 Cross-dimension synthesis

Four code defects compound into the observed waste profile, and none
requires more campaign data to fix:

1. **Inference is the systematically unpriced phase** (§3, §6) —
   uncalibrated fallback batch for generated models, 20/64
   pathological-unit verification failures — which feeds
2. **the SF-margin kill class** (§4): 35/36 kills within 5 % of
   deadline; SF 2.0 sits AT the measured P90 drift (2.05), so raising
   a fixed scalar never converges; which is made unrecoverable by
3. **`full_clone` formal inheritance freezing configs across retries**
   (§3): bit-identical params across 9+ consecutive paid failures —
   an executor defect, since the planner demonstrably adapts (96 %)
   when it is allowed to; while
4. **per-iteration observation-store roots** (§6) reset all calibration
   20× per chain, so the system can never learn the drift it keeps
   dying on; and the **delta gate** (§10) that should cut losses is
   unreachable because 15/17 iterations had no HealthGate-valid trial.

Science so far: `arch_10_14` is the campaign's one success (valid
formals 1.2954 → 1.3111, above its band raw floor). Band 4-9 is
collapse-bound on both flavors. Interim flavor verdict: arch > loss
in band 10-14; indeterminate in band 4-9.

---

## 1. §15.1 — Key-findings growth and evaluation

**Verdict: ⚠️ NEEDS ATTENTION (early-warning, qualified — applies to
the 04_09 pair; the 10_14 pair is too shallow to call at 3–4 iters).**

- **Discovery/promotion curve**: candidate vocab grew every iteration
  (+2 to +5), but **canonical promotions total 3 in 21 iterations —
  all at iteration 4, zero since** (`loss_04_09`:
  `spectral_consistency_loss`, `output_diversity_preservation`, log
  `:45842`; `arch_04_09`: `scalar_regression_head`, log `:19107`).
  `loss_10_14` produced zero promotions of any kind (no `Promoted `
  lines in its log). Canonical counts: 21→23 / 21→22 / 21→21 / 21→21.
- **Novelty classification** (all `RESEARCH REFLECTION` Discovery
  blocks): loss flavor 8 novel / 10 repeat / 2 vacuous; arch flavor
  11 / 12 / 3. **Iterations 1–3 supply 15 of the 19 novel
  discoveries**; iterations 4–7 supply 4. Token spend does not fall
  correspondingly (`loss_04_09`: 674 k → 1,006 k → 902 k over iters
  3–5) — the churn signature (flat/rising spend, falling novelty) is
  present in the 04_09 pair.
- **Strongest churn artifact**: `evolution_log.jsonl`
  `take_home_message` is a near-verbatim duplicate for 4–5
  consecutive iterations in every chain (e.g. `arch_04_09` iters 3–7
  all repeat the file-9 message).
- **Highest-value findings** (evidence rounds in the agent ledger):
  - Arch: learned-correction + moderate codebook temperature passes
    all gates AND beats prior best (`arch_10_14` i1, reproduced +
    sharpened at temp 12 / corr 0.2 at i3 → valid 1.3111); negative
    result that strengthening anti-collapse mechanisms worsens
    collapse (i3); the 256-class token head, not the backbone, is the
    collapse locus → scalar-regression pivot (`arch_04_09` i2→i5,
    −2.93 → −0.77).
  - Loss: `lambda_spec`→0.05 raises score via mode collapse — the
    sharpest quantified score-vs-gate tradeoff (`loss_10_14` i2);
    collapse vs pure generalization-gap distinguished (`loss_10_14`
    i2); per-file gates can pass while the aggregate collapses
    (`loss_10_14` i1).
- **Standard defects found**: `vocab_diversity_ratio` and
  `cumulative_information_gain` (named §15.1 sources) are **not
  emitted anywhere**; explore-mode is ON from iteration 1 in all 21
  iterations (byte-identical `Reasoning pipeline` line), so the
  "vocab stagnation triggers explore-mode" criterion is unevaluable
  as written.

**Recommendation**: re-check at ≥10 iterations before any V19 action
on the loop itself; fix the two missing metrics and the explore-mode
trigger so the criterion becomes evaluable.

## 2. §15.2 — ML literature-review adoption

**Verdict: ✅ PASS on both stated criteria (adoption ≉ 0; no
mis-grounding). Do not drop the node. Three sub-flags.**

- **Adoption ledger** (per-iteration, citation-verified in proposal
  `motivation`/`causal_hypothesis` fields; advice files verified to
  contain zero arxiv/doi tokens, so citations are provably
  lit-review-sourced): **11 of 22 proposals (50 %) adopt/adapt**; at
  finding granularity ≈ 23 % (11 of 48) adopted, 37 ignored.
- **Traceable payoff**: the classification-head → scalar-regression
  suggestion (adopted `arch_04_09` i2/i3/i5) is the only
  lit-review-traceable item that reached canonical vocab
  (`scalar_regression_head`) and preceded the chain-best −0.7748.
  No case of adoption preceding a worse round than its own baseline.
- **Sub-flag A — instrumentation**: `token_usage.jsonl` has **no
  lit-review label** in any workspace (labels: proposer, tuner,
  interpretation, implementor, validator only). The §15.2
  cost-benefit question is unanswerable until this is added.
- **Sub-flag B — retrieval monoculture**: `arxiv:2406.04378` (the
  TIDMAD paper) appears in 20/21 outputs and 10/11 cited proposals;
  only one genuinely new paper was ever adopted (`arxiv:2605.17582`,
  `arch_10_14` i4). `new_vocab_candidates == []` in 21/21 lit-review
  outputs. De-duplicate already-cited refs across iterations for V19.
- **Sub-flag C — availability**: 20/63 queries failed (32 %); mix
  HTTP 500 ×12, 429 ×5 (launch burst), 504 ×3; one total outage
  (`loss_10_14` i1, 0 findings). Retry/backoff on 5xx recovers most.

## 3. §15.3 — Failed attempts and failure reasons

**Verdict: ⚠️ NEEDS ATTENTION on both criteria.**

**Census** (226 attempt records in 17 closed iterations): 41 scored
rounds, 114 FREE failures, 71 PAID failures.

| Category | loss_04_09 | arch_04_09 | loss_10_14 | arch_10_14 | total | consumes attempt |
|---|---|---|---|---|---|---|
| FREE: Guardrail §5 skip (steps > 150 k) | 3 | 6 | 0 | 0 | 9 | yes |
| FREE: TimeEval pre-flight over-budget | 11 | 43 | 11 | 6 | 71 | yes |
| FREE: VRAMEval probe timeout (60 s) | 21 | 9 | 1 | 3 | 34 | yes |
| PAID: watchdog kill — training | 8 | 5 | 2 | 2 | 17 | yes |
| PAID: watchdog kill — inference | 3 | 3 | 7 | 3 | 16 | yes |
| PAID: in-subprocess `rejected_time_risk` | 5 | 11 | 13 | 9 | 38 | yes |
| PAID: mode collapse | 0 | 1 | 1 | 0 | 2 | yes |
| PAID: invalidated-under-production round | 12 | 14 | 6 | 4 | 36 | (round) |
| Gate exhaustion (iteration-level) | 1 | 4 | 2 | 1 | 8 iters | n/a |

Zero training crashes, zero CUDA OOM, zero impl-attempt exhaustion,
zero `[CHAIN] No models passed gates`.

- **Paid-failure wall share: 46.6 % / 38.6 % / 57.1 % / 47.7 %** per
  chain — all four exceed the ~25 % threshold; on both 10_14 chains
  the kill wall alone exceeds the productive wall.
- **Root causes**: RC-1 inference systematically under-priced (every
  TimeEval rejection names inference dominant; estimator warns
  `no registered inference batch … UNCALIBRATED` for generated
  models; completed-attempt inference ratio p90 2.71). RC-2 VRAMEval
  forward-probe 60 s timeouts, 62 % concentrated on `loss_04_09`
  (Python time-loop in `forward()` pattern). RC-3 **`full_clone`
  formal inheritance freezes the executed config** — attempts
  003→017 of `direct_logit_wavenet_budget_iter_002` are bit-identical
  across 9 rejections + 4 kills; the planner's `proposed_config`
  differs, so this is executor inheritance
  (`workflows/model_exploration.py:143,1397`), not planner blindness.
- **Planner-feedback check** (exhaustive consecutive-pair diff on
  runtime-relevant knobs): TimeEval 96 % adapted, VRAMEval 97 %,
  training kills 81 %, inference kills 60 %, **`rejected_time_risk`
  46 %** — every non-adapting cluster is a `full_clone` iteration.
- **>3× recurrence without adaptation: BREACHED** on `loss_10_14`
  (iter_002: 9× rejected + 3 inference kills, zero runtime-knob
  change) and `arch_10_14` (iter_002: 7× rejected + 2 kills,
  bit-identical).
- **Schema caveat for downstream consumers**: `is_trial` is `False`
  on every `attempt_failure` record including verified trial-round
  kills — trial/formal must be derived from `logical_round` + applied
  `safety_factor` (round 3/3 ⇔ formal, 180/180 log cases).

## 4. §15.4 — Killed attempts (watchdog ledger)

**Verdict: ⚠️ NEEDS ATTENTION on both criteria; the watchdog
mechanism itself is flawless.**

**36 kills** (33 structured + 3 log-derived in-flight), reconciled
three ways (log grep 11+10+10+5; training 18 + inference 18). Full
per-kill ledger with deadlines, elapsed, overrun, and estimate_source
is in the audit working set; deadline arithmetic spot-verified
against `core/sandbox_executor.py:408-440`
(`max(floor, min(operator_budget, Σ verified preds × SF))`).

- **By mode**: formal (SF 2.0) 31, trial (SF 3.0) 5. **By source**:
  `verified_components` 30, `operator_budget` 6 (all formal
  inference, 7200 s ceiling), floor-120 s 1.
- **Mandatory check — zero unbounded runaways: PASS** (41
  completed attempts re-checked; 0 exceedances without a kill).
  **Zero premature kills: PASS** (min overrun 1.0000 exactly).
  All 36 killed attempts carry `calibration_eligible: false` ✔.
- **Near-deadline share: 94.4 % training / 100 % inference** (<5 %
  overrun; median overrun **1.0002**). This is a systematic-margin
  signature, not tail noise: healthy, stably-verified attempts dying
  fractions of a second past the margin.
- **Formal kills recurred at SF 2.0** exactly as at 1.5 (§13h's
  trigger): e.g. `waveform_codebook_adapter_tcn_iter_002_011` killed
  at 4310.268 s vs deadline 4310.108 s. **Raising a fixed scalar SF
  is not converging** — measured long-run drift median 1.58 / P90
  2.05 (§6) puts SF 2.0 AT the P90 of the quantity it must bound.
  The 6 `operator_budget` inference kills are unfixable by any SF —
  they need smaller models / cheaper inference (exactly what the 8
  `gate_exhaustion` messages already demand).
- **Planner recovery rate**: trial kills 2/2; formal kills 7/31
  (22.6 %); non-recovering clusters = the `full_clone` iterations
  (§3 RC-3).
- **Two contract notes for V19**: (a) the watchdog arms per
  subprocess, so an attempt's TOTAL wall can legally exceed the
  7200 s formal budget — two admitted attempts did (~9,577 s and
  ~10,928 s); decide whether `operator_budget_seconds` is per-phase
  or per-attempt. (b) the 120 s floor can fire during verification
  when setup×SF lands under it (1 case, 133.7 s vs 120.0).

## 5. §15.5 — HealthGate behavior

**Verdict on the standard's central question ("gates too strict OR
models genuinely never healthy — decide which"): decided both ways,
by scope.**

- **Policy verified**: observe-mode both-continue on all four chains;
  effective YAMLs byte-identical root↔per-model; sha256 chains
  consistent lock↔manifest; per-scope monitored files = full scope
  (no `[3,10,17]` leak). **No round was invalidated anywhere** (all
  276 evaluations `resolved_action: continue`); "valid" below =
  would-pass-production. **40/46 gated rounds (87 %) would have been
  invalidated under production policy.**
- **Fire rates** (fired/evaluated): `output_diversity` 36/46 (78 %),
  `output_std` 32/46 (70 %), `amplitude_collapse` 12/46 (26 %),
  all three recording checks 0/46 (by construction). Binding
  constraint by scope: 04-09 = `output_std` (27/28 rounds under the
  1.0 mV floor; max ever 1.117 mV); 10-14 = `output_diversity`.
- **Valid-round rate**: loss_04_09 0/12, arch_04_09 0/16,
  loss_10_14 1/8, **arch_10_14 5/10 (50 %)**; cohort 6/46 (13 %).
- **Band 4-9: models genuinely unhealthy, gates correct.** Observed
  median uniq 5 / std 0.217 mV vs FCNet reference 75–81 / 2.70–3.00
  mV (15× / 13× shortfall — not a near-miss); 0 of 27 rounds reach
  the FCNet `pearson_dispersion` line (0.048); 22/28 rounds score
  below the band raw floor; two rounds are textbook mode collapse
  (uniq 1, std 0.000).
- **Band 10-14: 2 material false positives** — high-amplitude /
  low-diversity outputs rejected solely by the `min_unique_int8: 25`
  cutoff, a quadrant absent from the calibration set
  (`paper_and_collapse_reference_baselines.md` §3): `arch_10_14`
  i3 `003_007` (1.169) and i4 `004_005` (**1.303 — the campaign's
  single highest score**, uniq 16–20). Four further borderline cases
  in `loss_10_14` are immaterial (scores below the band floor). Two
  false negatives also noted (gate-valid noise-passthrough at 0.281
  and 0.022).
- **FORMAL-OVERRIDE ledger**: 7 formal rounds completed in the whole
  cohort; **7/7 ran under FORMAL OVERRIDE** (no iteration ever had a
  valid trial to promote). Two of the seven turned out gate-valid
  after the fact (both `arch_10_14`) — including the campaign-best
  valid 1.3111. Override warning counts: 48/81/17/3 per chain.
- **Recording checks → V19 §2.2 input**: `pearson_dispersion` is the
  most discriminating artifact in the audit — median 0.0056 (04-09,
  0 % above FCNet line) vs 0.0522 (10-14, 59 % above). Candidate
  blocking threshold ~0.02–0.03, or a rescue clause
  (`diversity FAIL AND pearson > 0.048 → record, don't invalidate`).
  `spectral_peak_ratio >> 1 AND pearson ≈ 0` exposes a
  synthetic-oscillator phantom signature no blocking gate catches
  (3 rounds, incl. `loss_04_09`'s best score 0.405).
  `amplitude_collapse_blocking` was **never the sole reason** a round
  failed — redundant as configured; tighten toward the FCNet max
  0.059 or switch aggregation to `all_pass` (m9 §9 Q1 deferred
  question, now with data).

## 6. §15.6 — Runtime-prediction quality (§2.10 contract)

**Verdict: ❌ contract broken in every predicted phase; V19 §3.1 is
urgent. Two code defects account for most of the damage.**

- **Component ratios (actual/predicted)**, completed attempts,
  kill-censored tail re-added as lower bounds: formal training P90
  **> SF 2.0 in all four chains** (2.02–2.19); trial inference P90
  3.39 in `arch_10_14` (> SF 3.0); pooled inference p90 2.85, max
  4.33. Long-run (≥500 s) drift: **median 1.58, P90 2.05** —
  reproduces the §13a 1.55–1.6× signature at 4-way; drift is
  duration-dependent (>1800 s runs: median 1.71).
- **Admission precision: 7/36 = 19 %** of admitted formal attempts
  finished in budget; 29 were watchdog-killed. Rejections: 38 (37
  known-cost lower bound, 1 fail-closed verification failure) — the
  §11 promise that a doomed formal costs ~1–2 min pre-flight HOLDS on
  the rejection path.
- **Defect 1 — no re-admission after inference verification**: six
  attempts admitted at `post_training_verification` then verified
  inference costs of 10,038–25,172 s (vs 7200 budget) and were
  allowed to run to the wall — **~12 GPU-hours of priced-impossible
  work**, the single largest cost line (40 % of kill wall).
- **Defect 2 — deadlines from partial component sets**: the watchdog
  deadline is Σ(components verified SO FAR)×SF, so 8 inference kills
  used training-only deadlines and 2 attempts were killed during
  verification on setup-only deadlines. 10 of 36 kills attributable
  to this alone (arithmetic verified per-kill).
- **Priors: structurally useless as deployed.**
  `runtime_policy.observation_store_root` is **per-iteration** (20
  distinct roots per chain) → `historical_prior` null in 120/120
  records; within-iteration match rate 20 % and falling by attempt
  ordinal; `evicted_drift` occurrences: 0 (rule unreachable).
  Latent hazard: `component_calibration_eligible` guards on
  `watchdog_status`, which the writer never sets.
- **Scoring phase: zero predictions/measurements** cohort-wide
  (`RuntimePhase.scoring` exists; never populated). **Setup ratio ≡
  1.0 by construction** (prediction copies measurement) — it enters
  admission sums as a tautology.
- **Setup spread claim inverted**: all 120 records are
  `warm_page_cache`; the 8 s → 476 s spread is
  `dataset_construction_seconds` under 4-way contention, and setup
  gets SLOWER as an iteration proceeds (first attempt median 34.9 s;
  later attempts median 77.0 s, max 476 s).
- **Provenance: the intact part of the contract** — SF 3.0/2.0,
  budget 7200 on formals only, watchdog config, H100/torch/CUDA
  uniform in 120/120 records.

## 7. §15.7 — Score progression and cross-scope comparison

**Verdict: ⚠️ partially tripped, interim. Band 4-9 is the band to
escalate. Trial-vs-formal criterion clean.**

**7.0 Method notes.** No published per-band official numbers exist
(`reference_data/official_paper_result/*.md` publish full-scope
only). Per-band comparators were derived by the canonical formula on
band-restricted support from `tidmad_official_banded/` — verified
exact against a chain's own `best_valid_file_vector` recomputation.
The 1.0007 raw floor is full-scope; recomputed band floors: **4-9 =
−0.0735, 10-14 = 1.0940** (GT ceilings 7.5113 / 9.7779). The chain
logs print `raw_scalar_full=1.0007` while running band-scoped — do
not use it as the bar.

**Trajectories** (trial best / formal best per closed iteration; ✓ =
HealthGate-valid):

- `loss_04_09` (4-9): formals −1.5744, −2.3543; trials to 0.4047;
  zero valid anything. 3 of 5 iters ended in time-gate exhaustion.
- `arch_04_09` (4-9): formals −1.5180 → −0.9902 (improving); trials
  to −0.7748; zero valid. 4 of 6 iters exhausted.
- `loss_10_14` (10-14): formal 0.2954 (invalid); best valid TRIAL
  0.4804 (i2).
- `arch_10_14` (10-14): **valid formals 1.2954 (i1) → 1.3111 (i3)** —
  the only valid formal scores in the campaign.

**Per-band standings** (per-band only, never mixed):

| Band 4-9 | score | Band 10-14 | score |
|---|---|---|---|
| GT ceiling | 7.5113 | GT ceiling | 9.7779 |
| official punet (derived) | 3.2731 | official fcnet (derived) | 6.6810 |
| official fcnet (derived) | 3.1008 | official rnn (derived) | 2.1323 |
| **raw floor** | **−0.0735** | **arch_10_14 valid formal** | **1.3111** |
| official rnn (derived) | −0.8528 | official punet (derived) | 1.1804 |
| arch_04_09 best formal ✗ | −0.9902 | **raw floor** | **1.0940** |
| loss_04_09 best formal ✗ | −1.5744 | loss_10_14 best formal ✗ | 0.2954 |

- **`arch_10_14` beats its band raw floor on a valid formal (+0.2171)
  and the derived official punet band figure (+0.1307)**; still 0.82
  below official rnn and 5.37 below fcnet.
- **Band 4-9: both chains below the band floor with zero valid
  results in 11 closed iterations** — the criterion's live concern.
  The bottleneck is HealthGate collapse (§5), not the flavor axis.
- **Flavor verdict**: band 10-14 — arch > loss, on valid evidence
  (2 valid formals vs 0; better conversion), n=3 each. Band 4-9 —
  indeterminate (orderings disagree, all evidence invalid).
- **Formal production**: 7/17 iterations (41 %) produced a formal
  score; 10/17 ended `aborted_fail_rounds`; 8 carry `gate_exhaustion`
  ("Model too large — … time gate"), all time-gated, none VRAM-gated;
  118 formal attempts `skipped_time_risk`.
- **Trial-vs-formal**: formal ≥ trial in 5/7 paired iterations,
  median gap **+0.1968 in formal's favour**; single outlier −2.54
  (60-segment trial snapshot flattered a spectral-loss config). No
  overfitting signature; but the delta gate keys on exactly this
  noisy trial quantity (→ §10).
- *Reconciliation note*: record-derived `skipped_time_risk` (118)
  exceeds `"Time check FAILED"` log lines (82); 36 skips persisted
  without the console print. Resolve before the final audit quotes
  either number.

## 8. §15.8 — Cost and resource accounting

**Verdict: ❌ estimate broken; wasted-wall threshold tripped;
resource envelopes untouched.**

- **Tokens** (from `token_usage.jsonl`, cross-checked to-the-token
  against `TOKEN_ITER` lines): campaign total **12,268,169** (529
  calls; 95.5 % prompt). Per fully-completed iteration: **613.6 k
  mean vs the §11 150–400 k band** (1.5–3.8× over). Pro-rated:
  ≈ 49 M for Wave 1 (4 chains × 20) or ≈ 98 M for all 8 chains vs
  the 13–32 M estimate. **12.27 M spent at 13 % of the plan already
  equals the low end of the whole-campaign estimate.** Role split:
  tuner 69.8 %, proposer 25.3 %, interpretation 2.4 %, implementor
  1.9 %, validator 0.5 %. Growth is super-linear within a chain
  (loss_04_09: 292 k → 1,006 k over iters 1–4). **Top lever: tuner
  prompt-context trimming / caching.**
- **Wall**: mean completed iteration **4.14 h** vs the 1–3 h §11
  band; four iterations exceeded 8 h (worst 12.4 h). All numbers are
  4-way-contention numbers (no 2-way era in this cohort).
- **Wasted wall: 39.5 % kills-only, 46.9 % incl. container-destroyed
  in-flight work** — every chain individually over the ~30 %
  threshold (55.3 / 51.7 / 42.3 / 38.4 %). Structure: 6
  `operator_budget` inference kills = 12.0 h (40 % of kill wall);
  30 near-deadline `verified_components` kills; 38 pre-flight
  rejections (cheap, working as designed); 3 health invalidations.
- **Envelopes**: never touched. Peak runner RSS 0.87–0.96 GB/chain
  (≈ 3.6 GB aggregate vs 251 GB cgroup limit, 1.5 %); VMS ~27 GB is
  RLIMIT_AS address space, not resident; zero VRAM/OOM/gate-storm
  events. §7's capacity audit is vindicated on resources —
  **but untested on two counts**: campaign-era `cpu.stat` throttle
  counters were destroyed by the container restart, and no numeric
  VRAM high-water mark is recorded anywhere (telemetry gap).
  Current cgroup readings are post-restart and describe a concurrent
  pytest run, not the campaign.

## 9. §15.9 — Protocol and provenance integrity

**Verdict: ✅ clean — no chain quarantined; comparative claims across
the four chains are valid.**

- **Provenance table**: locks (`run_invariants_lock.json`),
  manifests, observations, and the launcher command agree on every
  discriminating field — scope ([4-9] / [10-14]), monitored files =
  full scope, `health_gate_enabled: true`, per-scope
  `health_config_sha256` (`c04fbacc…` 04-09 pair / `e97da0ba…` 10-14
  pair), delta thresholds 0.0/0.5, trial SF 3.0 / formal SF 2.0 /
  floor 120 s / grace 10 / poll 1 in 120/120 observation records.
  Effective YAMLs byte-identical root↔per-attempt.
- **Archive isolation: verified clean.** Zero occurrences of
  `legacy_v18_*` / `halted_*` / `legacy_v18r_undersized` in all four
  chain logs and all live workspace files. The two same-name
  `loss_04_09` cohorts (halted SF-1.5 vs current) are provably
  disjoint (distinct roots, logs, run_ids; all paths absolute under
  the live workspace).
- **Queue-runner audit**: one log line (started 08:01:36, MAX_CONC=4,
  queue_len=4); no state file → zero launches, zero guard events,
  order fully pending as specified. (Restart hazard: §0.1.)
- **Gaps (uniform across all four chains — degrade the cohort
  equally, quarantine nothing)**:
  1. **Launch commit/branch recorded nowhere** (§15.9 requires it) —
     no claim in this audit can be pinned to a code revision.
  2. `chain_id` null in every observation.
  3. **`watchdog_status` never populated** (120/120) — the §15.4
     ledger is reconstructable only from the 7–10 MB logs, not the
     stores. Most consequential gap.
  4. Exit codes permanently unknown (container wipe).
  5. Cosmetic, reconciled: the launch banner prints stale gemini
     model defaults while all 529 recorded calls are openai gpt-5.4
     tier per `llm_configs/openai_tiered_v1.json` — fix the banner so
     it is not read as ground truth.

## 10. §15.10 — Delta-gate behavior against the fixed 0.0 reference

**Verdict: the fixed 0.0 reference was inert — and the binding
constraint is upstream of the reference value.**

- **Actual firings: 0 skips, 0 bypasses**, 17 iterations, 4 chains
  (log-verified; thresholds confirmed in every manifest and startup
  banner).
- **Why zero**: both gates route through `_best_trial_winner`, which
  requires a HealthGate-VALID trial. **15/17 iterations had none**,
  so the gates were unreachable regardless of the reference. The two
  reachable cases: `loss_10_14/002` (winner 0.4804 — no skip; missed
  bypass by **0.0196**) and `arch_10_14/002` (0.2813 — neither).
- **The near-miss is the section's key number**: after missing bypass
  by 0.0196, `loss_10_14/002` had 10 formal attempts time-rejected
  and closed with no formal score after **736.5 min** — the exact
  failure mode the bypass exists to prevent (code comment cites the
  v15 precedents).
- **Counterfactual (chain-local incumbent as reference, both
  definitions tested — valid-only and raw)**: exactly **one** formal
  round changes — `arch_10_14/002` (winner 0.2813 vs incumbent
  1.2954 → SKIP), reclaiming its **586.1 min** formal phase (63.8 %
  of that chain's wall; 14.4 % campaign-wide) at zero score cost.
  The three chains that most needed budget relief have
  `incumbent = None` and are unaffected.
- **Evidence package for V19 §2.4**: (1) fixed 0.0 is inert; (2)
  incumbent restoration is real but narrow — it only helps chains
  that already have a valid formal; (3) **any reference-policy change
  that does not also address trial-side HealthGate validity (or add
  a raw-score fallback) remains inert**; (4) the absolute Δ 0.5
  bypass threshold is miscalibrated to band scale — express it
  relative to the band floor/ceiling span.

---

## 11. Consolidated V19 recommendations (from all dimensions)

Runtime control (§3.1 class — urgent):
1. Assemble watchdog deadlines from a COMPLETE component set or fall
   back to `operator_budget` alone — never Σ(partial)×SF (10 kills).
2. Re-run admission at `post_inference_verification`; abort instead
   of running to the budget wall (~12 GPU-h saved here).
3. Move the observation-store root above the iteration directory so
   priors accumulate per chain (currently reset 20×).
4. Replace fixed scalar SF with duration-scaled or error-ledger
   margins (long-run drift median 1.58 / P90 2.05; SF 2.0 sits at
   the P90). Record GPU clocks/util in provenance to separate clock
   decay from contention (§13b.2).
5. Fix the inference pathological-unit heuristic (20/64 failures)
   and register inference batches for generated model types
   (UNCALIBRATED fallback drives the dominant-phase mispricing).
6. Populate `watchdog_status` (and `chain_id`) on observations; log
   the launch commit in the banner; decide per-phase vs per-attempt
   semantics for `operator_budget_seconds`.

Workflow / gates:
7. Let a formal retry re-plan RUNTIME knobs after a runtime-class
   failure while keeping the scientific config pinned (`full_clone`
   freeze is the recurrence-without-adaptation breach).
8. Incumbent restoration (issue #136 item 1) + a trial-validity
   fallback so the delta gates are reachable; band-relative bypass Δ.
9. HealthGate threshold study: `pearson_dispersion` as a blocking
   candidate (~0.02–0.03) or rescue clause; calibrate the
   high-amplitude/low-diversity quadrant (uniq 10–20 ×
   std/pearson-conditioned); fix `amplitude_collapse` redundancy
   (threshold toward 0.059 or `all_pass`).
10. Emit `vocab_diversity_ratio` / `cumulative_information_gain`;
    make the explore-mode trigger observable (§15.1 criterion is
    currently unevaluable).

Cost / instrumentation:
11. Tuner prompt-context trimming and caching (69.8 % of a 12.27 M
    spend that is 95.5 % prompt tokens); re-baseline the §11 token
    and wall estimates from measured numbers (613.6 k/iter, 4.14 h).
12. Add a lit-review token label; de-duplicate lit-review citations
    across iterations; S2 5xx retry/backoff.
13. Record a numeric VRAM high-water mark per attempt; resolve the
    118-vs-82 `skipped_time_risk` count discrepancy.

Operations:
14. Fix the two restart blockers (§0.1) before any relaunch:
    port launchers/queue runner off `screen` (or install it), and
    make the queue runner NOT advance state on a failed launch.

## 12. Audit provenance

- Standard: `reports/v18_20260724.md` §15 (+ §13a–§13h for cohort
  history). Ground rules honoured: no cross-scope aggregation; the
  SF-asymmetry note applies only to archived cohorts (this cohort is
  single-protocol per §13h); every claim cites a concrete artifact
  in the working evidence (chain logs by line, `run_output_*.json`
  records by exp_id, observation JSONL by attempt, manifests,
  locks).
- Evidence base: 4 chain logs (`v18r_*_20260724_075{7,9}.log`,
  grep-only), 17 `run_output_iter_*.json`, 21 manifests, 120
  observation records, 46 gated-round records, `token_usage.jsonl` /
  `memory_trace.jsonl` / `evolution_log.jsonl` / locks per
  workspace, `reference_data/official_paper_result/*.md`,
  `tidmad_official_banded/`, `raw_baseline/`, `ground_truth/`,
  live-host state (post-restart, labelled as such).
- Executed 2026-07-25 by six parallel audit passes (one per
  dimension group), synthesized 2026-07-25. INTERIM: the four
  in-flight iterations contribute to log-derived counts only; 13–17
  iterations per chain remain unexecuted; §15.1/§15.7 verdicts are
  explicitly qualified as early.
