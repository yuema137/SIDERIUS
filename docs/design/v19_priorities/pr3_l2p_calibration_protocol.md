# PR 3 — P3-L2p Pilot Calibration Protocol (Layer 2 pre-registration)

- **Status**: DRAFT — design only. NO LLM call or training run may be
  launched from this document until the operator approves the pilot
  (P3-L2p stop-and-show). Real-LLM launches additionally require the
  standing operator time-evaluation rule.
- **Parent**: [`pr3_healthgate_feedback.md`](pr3_healthgate_feedback.md)
  §4 (behavioral contract), §5 (budget skeleton), §7.2;
  baseline `v19_priorities.md` §4.2-§4.4.
- **Position**: Layer 2 is the MAIN source of broad quantitative
  behavioral calibration. Layer 3 (P3-L3) is a small end-to-end
  confirmation with real LLM and real training. **Synthetic outcomes do
  not replace real HealthGate outcomes**, and nothing in this pilot or
  the full campaign makes a production-improvement claim by itself.
- **Required proposer execution path**: the PRODUCTION 3-stage pipeline
  (`_run_pipeline`, `proposing_stage.md` template with the
  `healthgate_evidence_block` variable — the P3-V1 reopen-fix surface).
  Legacy 2-call mode is NOT an acceptable substitute; a pilot sample
  that fell back to legacy mode is invalid and re-run.

## 1. Purpose

The pilot is NOT an efficacy test. It exists to determine, before the
frozen full campaign:

1. scenario validity (do the two scenarios elicit scoreable behavior?);
2. metric observability (can every §5 metric be measured from the
   persisted artifacts?);
3. rubric clarity (can adjudication be applied without improvisation?);
4. runtime and cost per sample;
5. preliminary variance (crude, for sample-size arithmetic only);
6. schema-failure rate under the new prompt blocks;
7. whether the diagnostic arm reveals a delivery bottleneck
   (interpreter leg vs proposer leg).

## 2. Experimental arms

| Arm | Interpreter flag | Proposer flag | Role |
|---|---|---|---|
| Control (C) | OFF | OFF | pre-PR3 condition |
| Treatment (T) | ON | ON | full structured feedback |
| Diagnostic (D) — pilot only | ON | OFF | locates delivery-chain failures; excluded from any statistical comparison; the full campaign stays two-arm unless the pilot yields a concrete documented reason |

Arm-comparability rule: identical synthetic `ExperimentRecord`s,
identical carried history fixtures, identical seeds/model
configuration/sampling settings across comparable arms. The feedback
flag(s) are the ONLY difference. Arms run in separate scratch
workspaces (the run-invariants lock forbids in-workspace flips and the
artifact audit wants clean separation).

## 3. Pilot scenarios (exactly two)

Chosen for information density, not ease — jointly they cover repeated
same-fingerprint collapse, invalid high raw score, semantically
equivalent re-proposal, and model attribution / inappropriate
avoidance:

**S1 — Repeated diversity collapse with a deceptively high raw score
(single model).** `model_a` collapses in iterations N-1 and N with the
SAME fingerprint (`output_diversity_blocking:n_unique_int8_values=1`),
and the iteration-N collapse round carries a HIGH raw
`denoising_score` that is gate-invalid (the V17 "class-127 phantom"
family — the empirically dominant failure mode: 15/17 V18r iterations
had zero valid trials). Carried history enters iteration N with the
iteration-N-1 occurrence bucket, so the treatment proposer sees a
2-occurrence retained window. Probes: repeated-fingerprint
re-proposal; semantically equivalent re-proposal; invalid-high-score
handling (does the proposal treat the phantom score as success?);
explicit acknowledgment; mechanism change.

**S2 — Two-model attribution with a healthy alternative.** `model_a`
diversity-collapsed (fingerprinted); `model_b` healthy with a moderate
VALID score and a distinct mechanism. Probes: model attribution (is
model_a's evidence ever transferred to model_b?); inappropriate
avoidance (does the proposal abandon model_b's healthy mechanism
because model_a failed?); mechanism change grounded on the correct
model; unsupported use-claims.

Both scenarios reuse the CB-suite fixture vocabulary (real persisted
shapes, typed construction + `model_dump`), extended into full
`HyperparamTuningOutput` records per iteration.

## 4. Sample definition (one sample, precisely)

```text
fixed synthetic ExperimentRecords (per scenario, per iteration)
  → tuning_output_to_model_run_summary            [deterministic]
  → InterpretationInput (arm flags; carried typed history fixture;
     retention policy 3/8; iteration N)           [deterministic]
  → ResultInterpretationAgent.run()               [REAL LLM: per-model
                                                   call(s) + synthesis]
  → local_full_context(..., arm proposer flag,
     production ReasoningPipelineConfig)          [deterministic]
  → MLModelProposalAgent.run() PIPELINE mode      [REAL LLM: comparison,
                                                   causal, proposing]
  → parsed ProposalOutput                         [schema-validated]
  → deterministic scoring + blinded rubric        [no LLM]
```

Persisted per sample (one directory per sample id
`{scenario}_{arm}_{k}`): the input record fixtures (or their hash — the
fixtures are shared), the exact `InterpretationInput` dump, every
prompt SENT (captured at the bridge), every raw LLM response, the
`InterpretationOutput` dump, the `ProposalInput` dump, the parsed
`ProposalOutput` (or the schema-failure record + retry trail), token
usage rows, wall-clock timestamps, and the deterministic-scoring
record. Nothing is scored from memory; adjudication reads artifacts.

Per-sample LLM calls (pipeline mode, counted from code):

| Scenario | Interpreter | Proposer (pipeline) | Total |
|---|---|---|---|
| S1 (1 model) | 1 (per-model; synthesis skipped for a single model) | 3 (comparison, causal, proposing) | 4 |
| S2 (2 models) | 3 (2 per-model + 1 synthesis) | 3 | 6 |

## 5. LLM configuration (pre-registered; frozen at pilot approval)

| Setting | Value | Source |
|---|---|---|
| Provider | `openai` | production chain standard (CLAUDE.md launch command; Gemini deprioritized per operator stability memo) |
| Model (interpreter + proposer) | `gpt-5.5` | production chain standard `--model_id` |
| Model version string | pinned from the FIRST pilot API response and recorded here before further samples | — |
| temperature / top-p / max tokens | provider API defaults — `LLMBridge` sets none (verified: `agent/llm_bridge.py` passes no sampling params) | code |
| Random seed | not supported through the bridge; stochasticity is measured, not suppressed | code |
| Retry policy | bridge envelope `max_retries=3` (interactive posture — NOT the chain's infinite-quota mode); SDK-internal retries disabled (`max_retries=0` at the SDK layer) | code |
| Schema repair | the node's own validation-retry loops as in production (proposing-stage structural retries); each retry COUNTS toward the call cap | code |
| Timeout | bridge/provider defaults (unchanged) | code |
| Concurrency | 1 (serial samples — clean per-sample token/latency attribution) | protocol |

Revision rule: none of these may change after observing favorable or
unfavorable results without a documented protocol revision in this
file.

## 6. Metrics

**Class 1 — direct behavioral (per sample, from artifacts):**
repeated-collapse-fingerprint proposal rate (deterministic where
possible + rubric); semantically-equivalent-repeat rate (rubric);
actual mechanism-change rate (deterministic field comparison, §7);
explicit-acknowledgment rate (does the motivation cite the fingerprint
string?); wrong-model / stale-evidence attribution rate (rubric with
deterministic pre-screen: fingerprint strings vs model sections);
unsupported-use-claim rate (claims feedback use in an arm whose prompt
contained none — control-arm probe); inappropriate-avoidance rate
(S2: abandoning model_b's healthy mechanism citing model_a's failure);
schema-validation failure rate (count of validation-retry loops +
terminal failures).

**Class 2 — synthetic downstream outcome:** the pilot's pseudo
environment assigns NO next-round outcome (no training, no scoring).
If the FULL campaign later adds a scripted outcome, it will be labeled
**SYNTHETIC OUTCOME** everywhere — it is never a real
HealthGate-valid rate and is never reported as one.

**Class 3 — operational:** input/output tokens per call and per
sample; wall-clock latency per call and per sample; retry count; parse
failures; API cost (from token usage × current price sheet).

## 7. Genuine-use scoring (pre-registered mechanism relevance)

Success is NEVER scored from explanation text alone. Deterministic
comparison against the failed configuration decides "mechanism
changed"; text can only upgrade (acknowledgment) or downgrade
(unsupported claim) — never substitute.

Pre-registered relevant-mechanism fields per scenario (a proposal
counts as a mechanism change iff at least one changes vs the
fingerprinted configuration, compared on the parsed
`ProposalOutput.baseline_config` + architecture identity):

- **S1 (output-diversity collapse)**: architecture family (model_name
  lineage / structural class); output activation; output-layer
  normalization; loss (`loss_config.loss_type` or a populated
  `custom_loss_spec`); optimizer/lr policy (`train_config.lr`,
  optimizer fields); training budget fields (`epochs`).
- **S2 (attribution)**: as S1 for the model_a-derived parts, PLUS the
  deterministic checks: does the proposal inherit/extend model_b's
  named healthy mechanism (presence of its component in
  `mathematical_definition`/`inherited_components`), and does any
  model_a fingerprint string or metric appear attributed to model_b?

## 8. Rubric procedure

- **Labels** (per sample): `genuine_change` / `superficial_compliance`
  / `repeat_equivalent` / `misattributed` / `inappropriate_avoidance`
  / `unscorable` (+ free-text note).
- **Superficial compliance** (pre-defined): mentions the fingerprint
  but proposes a semantically equivalent mechanism; copies numbers
  with wrong attribution; claims avoidance with no concrete mechanism
  named; paraphrases that lose the discriminating number; explanation
  changed while `baseline_config`/architecture did not.
- **Adjudication instructions**: read ONLY the persisted
  `ProposalOutput` + the deterministic pre-screen record; the rubric
  decides semantic equivalence and mechanism relevance ONLY where the
  deterministic comparison is inconclusive.
- **Blinding**: the evaluator sees the proposal and the scenario
  fixture but NOT the arm label (prompts are withheld from the
  adjudication view; deterministic pre-screen output is
  arm-label-free). Practical for this pilot because scoring reads the
  parsed output, not the prompt.
- **Reviewers**: one blinded reviewer for the pilot (rubric-clarity is
  itself under test); every `unscorable` or borderline sample is
  flagged verbatim in the pilot report. The FULL campaign uses two
  reviewers on a disagreement-prone subset with reported inter-rater
  disagreement; the pilot decides that subset's definition.
- **Ambiguity**: ambiguous samples are labeled `unscorable`, never
  force-labeled; ≥20% unscorable is a redesign trigger (§10).

## 9. Pilot budget (hard cap unchanged: 60 calls)

Pipeline mode raises calls-per-sample above the original 2-call sketch
(S1=4, S2=6 — §4), so sample counts are set to honor the SAME 60-call
hard maximum rather than silently exceeding it:

| Scenario | C | T | D | Samples | Calls |
|---|---|---|---|---|---|
| S1 (4 calls/sample) | 2 | 2 | 1 | 5 | 20 |
| S2 (6 calls/sample) | 2 | 2 | 1 | 5 | 30 |
| **Nominal total** | | | | 10 | **50** |
| Retry/schema-repair allowance | | | | | 10 |
| **Hard maximum** | | | | | **60** |

Estimates (validated by the pilot itself): ~4-8k input + ~1-3k output
tokens per call (the proposing stage dominates); expected wall time
≈ 1-3 min/sample serial → 15-40 min total; expected API cost is
recorded against the live gpt-5.5 price sheet at freeze time and
entered here before launch (the token arithmetic, not a guess, is the
estimate's basis). Stop conditions: the 60th call (hard stop,
mid-sample abandonment recorded); any provider auth/quota failure
loop; two consecutive samples with terminal schema failure.

## 10. Pilot redesign triggers (any one → stop, report, redesign before P3-L2)

- outputs cannot be scored reliably (≥20% `unscorable`);
- arms are not cleanly separable (evidence text leaks into C, or T
  prompts lack the block — delivery regression);
- terminal schema-failure rate > 20% of samples;
- strong ceiling/floor (e.g. every C sample already avoids the
  fingerprint → scenario has no headroom; or no T sample ever changes
  a mechanism → prompt too weak to calibrate);
- treatment changes wording only (mechanism-change rate ≈ 0 while
  acknowledgment rate is high);
- token cost per sample exceeds 2× the §9 estimate;
- the diagnostic arm shows the interpreter leg drops/paraphrases the
  fingerprint before the proposer ever sees it.

## 11. Full-campaign decision rule (frozen BEFORE the campaign)

From pilot measurements: per-metric sample proportions and their
crude variance set **samples per scenario** via a normal-approximation
two-proportion power sketch at the pre-registered effect size
(minimum interesting difference: 0.3 absolute on
repeated-collapse-fingerprint rate — chosen from the §4 hypothesis
that structured evidence should prevent MOST identical-fingerprint
repeats, not marginally reduce them); Wilson intervals for reporting;
Holm correction across the primary-metric family. **Primary
(activation-relevant) metrics**: repeated-collapse-fingerprint rate +
actual mechanism-change rate; all others are secondary/diagnostic.
The pilot also decides whether all eight §4.2-subset scenarios remain
in the campaign or any are consolidated (documented per scenario).
The campaign's final call/cost cap is set from measured per-sample
cost × the computed sample plan, submitted for operator approval, and
FROZEN — thresholds are never chosen after seeing campaign outcomes.

## 12. Layer-3 boundary (restated)

Layer 2 provides the broad quantitative behavioral calibration under
controlled synthetic evidence. Layer 3 (P3-L3) is a SMALL end-to-end
confirmation: real LLM, real training, real HealthGate results, real
persisted context across a real iteration boundary — designed after
P3-L2, cold-start, operator-approved before any launch. Synthetic
outcomes never substitute for real HealthGate outcomes, and no
valid-round-rate claim is made from Layer 2 alone.
