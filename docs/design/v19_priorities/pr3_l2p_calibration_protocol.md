# PR 3 — P3-L2p Pilot Calibration Protocol (rev 2 — operator revision 2026-07-29)

- **Status**: DRAFT rev 2 — design only, awaiting operator approval.
  NO LLM call or training run may be launched from this document until
  the operator gives an explicit pilot-launch decision.
- **Parent**: [`pr3_healthgate_feedback.md`](pr3_healthgate_feedback.md)
  §4/§5/§7.2; baseline `v19_priorities.md` §4.2-§4.4.

## 0. Governing calibration principle

**Agent-system behavior must be measured empirically. Adding a module,
field, schema, or prompt block does not establish that the agent uses
it correctly or that behavior improves.**

The three validation layers have different roles:

- **Layer 1** — deterministic correctness and information delivery
  (closed: P3-V1).
- **Layer 2** — broad quantitative calibration with REAL LLMs and
  controlled pseudo training/scoring. This is the PRIMARY source of
  statistical coverage, because difficult, rare, and conflicting
  feedback combinations can be constructed deliberately and repeated
  cheaply. Layer 2 is not merely a cheap integration test.
- **Layer 3** — a SMALL real-LLM + real-training confirmation that the
  Layer-2 behavior survives the true production system. Layer 3 is
  never the primary source of statistical power.

**Synthetic outcomes must never be reported as real HealthGate-valid
outcomes.**

## 1. Pilot goals and non-goals

The pilot is NOT an efficacy test and must not be used for activation.
No statistical significance is required from it, and PR 3 is never
declared behaviorally successful from pilot results.

Goals: verify both scenarios are behaviorally informative; verify
metric observability; validate the deterministic scorer; test rubric
clarity; estimate response variance; estimate parse/schema failure
rates; measure call counts, latency, tokens, cost; detect
ceiling/floor effects; detect wording-only treatment effects;
determine whether the diagnostic arm identifies a delivery bottleneck;
estimate the practical full-campaign sample size.

## 2. Experimental arms

| Arm | Interpreter flag | Proposer flag | Role |
|---|---|---|---|
| Control (C) | OFF | OFF | pre-PR3 condition |
| Treatment (T) | ON | ON | full structured feedback |
| Diagnostic (D) — pilot only | ON | OFF | delivery-chain localization ONLY (§12) |

Comparability: identical synthetic records, carried-history fixtures,
retention policy (3/8), model configuration, and sampling settings
across comparable arms; the feedback flag(s) are the ONLY intended
difference. Arms run in separate scratch workspaces.

**Seed statement**: the provider API offers no honored random-seed
control through `LLMBridge`. Samples are therefore **independent
stochastic repetitions under identical configuration, not paired-seed
samples** — no "paired" language applies anywhere in this study.

## 3. Pilot scenarios (exactly two)

**S1 — Repeated diversity collapse with a deceptively high invalid raw
score (single model).** `model_a` collapses in iterations N-1 and N
with the same fingerprint
(`output_diversity_blocking:n_unique_int8_values=1`); the iteration-N
collapse round carries a HIGH raw score that is gate-invalid (the V17
"class-127 phantom" family — the empirically dominant failure mode).
Carried history gives the treatment proposer a 2-occurrence retained
window. Probes: repeated-fingerprint re-proposal; semantic-equivalent
re-proposal; invalid-high-score handling; acknowledgment; mechanism
change.

**S2 — Two-model attribution with a healthy alternative.** `model_a`
diversity-collapsed (fingerprinted); `model_b` healthy with a VALID
moderate score and a distinct named mechanism. Probes: attribution;
inappropriate avoidance; correct-model mechanism grounding;
unsupported use-claims.

Fixtures are typed constructions serialized with `model_dump` (real
persisted shapes — the CB-suite vocabulary), frozen before launch.

## 4. Sample definition (normative)

```text
fixed synthetic ExperimentRecords                     [deterministic]
→ tuning_output_to_model_run_summary /
  InterpretationInput construction                    [deterministic]
→ ResultInterpretationAgent.run()                     [REAL LLM]
→ deterministic InterpretationOutput health fields    [deterministic —
                                                       computed outside
                                                       the LLM path]
→ local_full_context(...) protocol                    [deterministic]
→ MLModelProposalAgent.run() — PRODUCTION
  PIPELINE MODE (_run_pipeline, stage-template
  assembly, proposing_stage.md)                       [REAL LLM ×3]
→ parsed ProposalOutput / configuration               [deterministic]
→ deterministic scoring                               [deterministic]
→ blinded rubric scoring where required               [human]
→ persisted sample artifact bundle                    [deterministic]
```

**Protocol invariant (production path)**: *Every pilot and
full-campaign proposer sample must use production pipeline mode. The
captured proposing-stage prompt is an auditable artifact for every
sample.* A sample that used `_build_reasoning_prompt()` or legacy mode
is INVALID for the study (recorded as invalid, never scored, and its
calls still count against the cap).

**Persisted per sample** (`{scenario}_{arm}_{k}/`): proposer execution
mode; every stage prompt; the final proposing-stage prompt; the
resolved template variables; the exact `InterpretationInput` and
`ProposalInput` dumps; every raw LLM response; retry history with
reasons; parsed `ProposalOutput` (or terminal-failure record);
response-reported model/version metadata; token usage; timestamps;
the deterministic-scoring record. Arm and scenario identifiers live in
a SEPARATE evaluation manifest; the scoring copy given to blinded
reviewers exposes neither the arm label nor arm-revealing
paths/filenames (§11 notes the inherent-blinding limit).

## 5. Frozen LLM configuration and version policy

| Setting | Value |
|---|---|
| Provider | `openai` (the intended production configuration for this study; matches the standard chain launch) |
| Model | `gpt-5.5` (interpreter AND proposer) |
| Model-version identifier | persisted from EVERY response; the pilot's registered version is pinned from the first response before further samples |
| temperature | **not set by the bridge; provider default used** |
| top-p | **not set by the bridge; provider default used** |
| max output tokens | **not set by the bridge; provider default used** |
| reasoning effort / equivalent | **not set by the bridge; provider default used** |
| timeout | bridge/provider defaults, unchanged |
| Concurrency | serial (1) — clean per-sample token/latency attribution |
| Schema validation | the nodes' production Pydantic validation, unchanged |
| Schema repair | the nodes' production validation-retry loops, unchanged; each repair call IS an LLM call and counts toward the 60-call cap |
| Retry conditions | §6 only |
| Maximum retries | bridge envelope `max_retries=3` per call (interactive posture — not the chain's infinite-quota mode) |

**Version-drift rule**: if the service-reported model/version changes
during the pilot, STOP before pooling samples across versions and
request operator review. Model versions are never mixed in one
analysis without an explicit protocol revision.

No setting above may change after observing favorable or unfavorable
results without a documented protocol revision.

## 6. Retry semantics (narrow, pre-registered)

Retries are allowed ONLY for: transport/API failure; timeout; empty
response; unparseable response; schema-validation failure; documented
transient provider error.

Retries are NEVER allowed because: the answer is low quality; the
proposal repeats the failed mechanism; the treatment appears
ineffective; the evaluator dislikes a valid output; the result is
unfavorable to the hypothesis.

Accounting: a schema-repair call IS a retry and IS an LLM call; both
count toward the 60-call hard cap. Every failed attempt is retained
with its reason; sample-level and call-level failure rates are
reported. **The sample output is the first schema-valid response**; a
valid response is never replaced, silently or otherwise.

## 7. Sample allocation and call arithmetic (exact)

Per-sample LLM calls in production pipeline mode (counted from code;
NOT the earlier legacy-mode sketch): S1 = 1 interpreter (single model;
synthesis skipped) + 3 proposer = **4**; S2 = 3 interpreter (2
per-model + 1 synthesis) + 3 proposer = **6**. Diagnostic samples run
the full pipeline (the proposer executes with the flag OFF), so they
cost the same as C/T samples.

| Scenario | Arm | Repetitions | Interp calls/sample | Proposer calls/sample | Nominal calls |
|---|---|---|---|---|---|
| S1 | C | 2 | 1 | 3 | 8 |
| S1 | T | 2 | 1 | 3 | 8 |
| S1 | D | 1 | 1 | 3 | 4 |
| S2 | C | 2 | 3 | 3 | 12 |
| S2 | T | 2 | 3 | 3 | 12 |
| S2 | D | 1 | 3 | 3 | 6 |
| **Total** | | **10** | | | **50** |

Nominal 50 ≤ 50 ✓; retry/schema-repair allowance 10; **hard maximum
60** — retries count against it, and NO unlisted exploratory calls are
permitted. Diagnostic samples never enter the C-vs-T efficacy
comparison.

Allocation rationale: samples are BALANCED per scenario and per C/T
arm (2/2); only D is smaller (1 per scenario) because it is a
qualitative delivery-localization probe, not a compared arm. The
scenarios' call totals differ (20 vs 30) purely because S2's
two-model interpreter leg costs more per sample — an unequal
CALL split, not an unequal sample design.

## 8. Metrics — three classes with explicit denominators

Handling rules common to all rates: terminal-invalid parsed outputs
and `unscorable` samples are EXCLUDED from behavioral-rate
denominators and reported as their own rates (never treated as
success); retries do not create extra denominator entries (one sample
= one output); there are no abstentions in this design (a sample
either yields a schema-valid proposal or is a terminal failure);
missing proposals = terminal failures.

**8.1 Direct behavioral (primary Layer-2 outcomes)** — per metric:
numerator / denominator:

- Repeated-collapse-fingerprint proposal rate — samples whose proposal
  reproduces the fingerprinted mechanism (deterministic pre-screen +
  rubric) / samples whose supplied history contains a collapse
  fingerprint and where a repeat is meaningfully possible (all S1+S2
  samples with valid parsed proposals).
- Semantically equivalent repeat rate — rubric `Semantically
  equivalent repeat` labels / same denominator as above.
- Actual relevant mechanism-change rate — samples whose parsed
  proposal/config changes ≥1 pre-registered relevant mechanism (§9,
  deterministic) / samples with a valid parsed proposal and a defined
  relevant-mechanism set.
- Explicit acknowledgment rate — samples accurately acknowledging the
  supplied failure evidence / samples where the evidence was actually
  visible to that agent arm (T proposer samples; interpreter-side
  acknowledgment measured separately on T+D). **C and D proposer
  outputs are NEVER counted as acknowledgment failures** — no
  acknowledgment was possible; they instead feed the
  unsupported-use-claim metric.
- Wrong-model attribution rate — samples attributing model_a evidence
  to model_b or vice versa / S2 samples (≥2 distinguishable models)
  with valid parsed proposals.
- Stale-evidence attribution rate — samples citing evidence from an
  iteration/model not present in the supplied window / T samples with
  valid parsed proposals.
- Unsupported-feedback-use claim rate — samples whose explanation
  claims use of structured feedback that their arm's prompts did not
  contain / C and D-proposer samples with valid parsed proposals.
- Inappropriate-avoidance rate — S2 samples abandoning model_b's
  healthy mechanism citing model_a's failure / S2 samples with valid
  parsed proposals.
- Schema-validation failure rate — reported at BOTH levels: failing
  calls / all calls, and terminal-failure samples / all samples.

**8.2 Synthetic downstream outcomes** — the pilot assigns NONE (no
training, no scoring; neither scenario needs one). If the full
campaign adds a scripted next-round result, it is labeled **synthetic
downstream outcome** everywhere and never called a HealthGate-valid
rate, real valid-round rate, or real score improvement.

**8.3 Operational** — interpreter and proposer input/output tokens;
total tokens per sample; latency per call and per sample; retry count;
parse failures; schema-repair calls; API cost; **prompt-length
increase from treatment** (measured: ≈1.8k chars ≈ 460 tokens on the
dry render — §14).

## 9. Pre-registered mechanism-relevance map (frozen at pilot approval)

Deterministic comparison of the parsed proposal/config against the
fingerprinted configuration decides "mechanism changed"; explanation
text can only upgrade (acknowledgment) or downgrade (unsupported
claim) — never substitute.

**S1 (output-diversity collapse)** — counts as relevant: output
activation change; output quantization/clipping behavior;
normalization scheme; architecture output head / family; loss terms
plausibly tied to diversity or variance (incl. a populated
`custom_loss_spec`); optimizer/training-policy changes plausibly
addressing collapse (lr regime, epochs); another mechanism ONLY with
an explicit collapse link adjudicated by rubric. Does NOT count:
renaming the model; superficial layer-count change with the same
output mechanism; explanation-only change; unrelated data-order
changes without a mechanism link; changing an irrelevant
hyperparameter to appear different.

**S2 (attribution/avoidance)** — relevant success: correctly
identifying which model produced the fingerprint; modifying the FAILED
model's relevant mechanism (S1 list); preserving or building on
model_b's named healthy mechanism (its component present in
`mathematical_definition`/`inherited_components`) rather than avoiding
both; not transferring model_a's collapse diagnosis to model_b.

This map is FROZEN before execution; changing it mid-pilot requires
stopping and revising the protocol before further samples.

## 10. Deterministic scoring before rubric scoring

Deterministic scorer (typed-field comparison; outputs its own record,
separate from the rubric): exact fingerprint/gate-name reference
present; model names referenced vs supplied; architecture-family
change; output-activation change; normalization change; loss change
(`loss_type` / `custom_loss_spec`); optimizer-policy change
(`train_config` fields); schema validity; presence of treatment-only
evidence strings in C-arm outputs (leak check); proposal equality on
typed fields vs the fingerprinted config. Determinism check: the
scorer re-run on identical artifacts must produce identical records
(a §17 stop condition if not).

Rubric-only judgments: semantic equivalence despite different syntax;
plausible collapse-relevance of a novel mechanism; inappropriate
avoidance; indirectly-expressed unsupported claims; whether the failed
mechanism materially changed. The deterministic scorer and the rubric
output SEPARATE fields — never one collapsed subjective success label.

## 11. Blinded rubric

**Sample-level labels** (multiple failure labels allowed):
`Genuine relevant change` / `Superficial compliance` /
`Semantically equivalent repeat` / `Wrong attribution` /
`Inappropriate avoidance` / `Unsupported use claim` /
`Valid but irrelevant change` / `Unscorable`.

Adjudication: the reviewer reads ONLY the scoring copy — parsed
proposal + scenario fixture + deterministic-scorer record (arm-free)
— never the prompts or arm labels, and is not told the study
hypothesis. Required evidence per label: each label must cite the
specific proposal/config field or quoted sentence that grounds it.
Explanation text is supporting evidence only; proposal/config fields
decide mechanism questions. Ambiguity → `Unscorable` + verbatim note,
never force-labeled.

Reviewers: one blinded reviewer scores every sample; **all ambiguous
samples and all rubric-primary samples (any sample whose primary
metrics depend on a rubric judgment rather than the deterministic
scorer) receive a second review**. Disagreements are resolved by
discussion to an adjudicated label; RAW agreement and adjudicated
results are reported separately.

Blinding limit (stated plainly): a treatment proposal may itself quote
fingerprint text, making arm inference possible from content — perfect
blinding is impossible; the manifest/path hygiene above removes every
avoidable channel.

## 12. Diagnostic arm — role and restrictions

Interpreter ON / proposer OFF. It answers ONLY: did the interpreter
preserve the fingerprint accurately in its LLM text? were the
deterministic fields populated? did the proposer output remain
control-like without the block? do unsupported-use claims appear with
no proposer-visible block?

Restrictions: never enters the C-vs-T efficacy comparison; a
favorable diagnostic sample is never evidence that the full treatment
works; diagnostic findings never alter the already-running pilot —
any change they motivate requires stopping and revising this protocol
before further samples.

## 13. Effect-size interpretation and analysis boundaries

**0.30 absolute difference is a PLANNING effect size** — used to
assess whether a full campaign is practically worthwhile and to
estimate sample requirements. It is NOT a pilot significance
threshold, NOT an activation threshold, NOT proof of improvement, and
NOT a reason to stop early on a few favorable samples.

Pre-registered primary hierarchy it applies to:

- **Primary 1**: repeated-collapse-fingerprint rate DECREASES (T vs C).
- **Primary 2**: relevant mechanism-change rate INCREASES (T vs C).
- **Safety constraints** (must not materially worsen): wrong
  attribution, inappropriate avoidance, unsupported-use claims, schema
  failures, token cost.

Full-campaign "worthwhile" requires Primary 1; Primary 2 corroborates.
No composite score exists (none is pre-registered).

**Analysis boundaries**: pilot results are DESCRIPTIVE — simple
proportions with at most an informal uncertainty summary; no formal
efficacy conclusion. Wilson confidence intervals and Holm correction
belong to the FROZEN full campaign only, applied to its pre-registered
comparison family (listed in the full-campaign protocol before it
runs: the two primaries + the named safety constraints, T vs C). No
multiple-testing machinery is applied to exploratory pilot
observations.

## 14. Complete pilot cost table

Grounded by a deterministic dry render (2026-07-29, zero LLM calls:
the exact stage prompts for one sample per scenario/arm were assembled
through the real production pipeline and measured; chars/4 ≈ tokens).
Caveat recorded: the proposing-stage prompt embeds this machine's live
plugin/loss registries (57 plugins at render time), which dominate its
size; the launch-day dry render re-measures with the then-current
registry.

| Item | S1 | S2 | Total |
|---|---|---|---|
| Nominal samples | 5 | 5 | 10 |
| Interpreter calls | 5 | 15 | 20 |
| Proposer calls | 15 | 15 | 30 |
| Nominal LLM calls | 20 | 30 | 50 |
| Retry allowance | — | — | 10 |
| **Hard maximum calls** | | | **60** |
| Est. input tokens / sample | ≈115k (proposer 3-stage ≈113k + interp ≈2k) | ≈120k (+ interp ≈6k) | ≈1.2M nominal |
| Est. output tokens | method: unknown a priori — measured from the pilot's first sample per scenario; planning bound 1-3k/call → 15-45k total | | |
| Est. wall time | serial, 1-3 min/sample | | ≈15-40 min |
| Est. API cost | method: input/output token totals × the live gpt-5.5 price sheet, computed and entered here at launch-day freeze — no ungrounded number | | |
| Treatment prompt increase | measured: ≈1.8k chars ≈ 460 tokens (proposer) | | |

## 15. Pilot-to-full-campaign transition rule

The full L2 protocol is a SEPARATE document, frozen before the
campaign runs. The pilot report must provide: per-arm rates for every
metric with eligible-sample counts; parse/schema failure rates;
unscorable rate; token and cost distributions; scenario ceiling/floor
observations; preliminary T-C differences (descriptive); rubric raw
agreement; model/version consistency; actual calls consumed.

Full-campaign sample size derives from: the pre-registered primaries;
the 0.30 planning effect; a target interval precision or justified
power criterion; observed pilot variance (used cautiously — the pilot
is small); scenario count; the operator-approved call budget; the
observed retry rate. Never a pilot size × arbitrary factor.

Decision outcomes: **Proceed unchanged** (both scenarios scorable,
costs acceptable, no major ceiling/floor or rubric problem) /
**Revise before full campaign** (a scenario, scorer, rubric, or prompt
condition is uninformative or unreliable — revised before the full
protocol freezes) / **Stop the study** (treatment cannot be isolated;
production execution unstable; excessive schema failures; rubric
unreliable; expected cost exceeds the approved bound). Any scenario
added, removed, or rewritten after the pilot is documented before the
campaign starts.

## 16. Explicit pilot stop conditions

Stop before the maximum if ANY occurs: production pipeline mode not
used; model/version metadata changes; cumulative calls reach 60;
repeated technical failures make the remaining allocation impossible;
schema-valid output rate falls below the pilot floor (< 70% of calls);
treatment/control inputs differ beyond the intended flag; persisted
artifacts incomplete; arm labels leak into blinded evaluation files;
a production defect is discovered; token or monetary cost exceeds the
hard cap; the deterministic scorer produces inconsistent results on
identical artifacts.

Stopping is not failure concealment: all collected artifacts are
preserved and the reason reported. Stopped samples are never silently
replaced.

## 17. P3-S boundary (merge vs behavioral validation)

P3-S may proceed independently once the final CI is green. The merge
claim is LIMITED to: *Layer-1 structured-evidence plumbing implemented
and deterministically validated, with the production flag OFF by
default.* Merge does NOT mean PR 3 is complete, that structured
feedback improves behavior, that the treatment should be activated,
that this pilot is approved, or that the default may change. Stages
remain separate: P3-S (Layer-1 merge, flag OFF) → P3-L2p (this pilot)
→ P3-L2 (full calibration) → P3-L3 (small real-training confirmation)
→ P3-ACT (separate operator activation decision).

## 18. Remaining TBD values (resolved BEFORE launch, none during)

| TBD | Resolution method |
|---|---|
| Model-version string | pinned from the first pilot response |
| Output tokens / API cost | launch-day dry render (input) + live price sheet + first-sample-per-scenario measurement (output) |
| Registry-dependent prompt size | launch-day dry re-render against the then-current plugin/loss registries |
| Scenario fixture freeze | fixtures committed to the repo before the launch request |
