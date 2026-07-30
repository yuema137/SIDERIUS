# PR 3 — Full Layer-2 Descriptive Quantitative Calibration Protocol (FROZEN)

- **Status**: FROZEN 2026-07-29 (operator-named file, per the full
  execution plan §4). Committed BEFORE the first campaign LLM call.
  Launch proceeds without further routine approval once the zero-LLM
  preflight is green (operator plan §5); the frozen stop conditions
  (§10) are the only interruption triggers.
- **Parents**: `pr3_l2p_calibration_protocol.md` (pilot protocol; its
  §5 frozen LLM config, §6 retry semantics, §11 blinding, §16
  determinism rules, §24/§24.1 attribution audit, and §25 budget/
  reporting rules carry over verbatim unless restated here);
  `pr3_healthgate_feedback.md` §0/§4/§7.
- **Nature (binding)**: **descriptive quantitative calibration** — NOT
  a fully powered confirmatory study for a 0.30 absolute effect. No
  significance machinery is used for claims; a CI crossing zero is
  never reported as "no effect"; scenario heterogeneity is reported,
  never hidden behind a pooled average; pooled summaries appear only
  where scientifically justified and are always accompanied by the
  scenario-level tables.

## 1. Objective

Measure whether structured HealthGate feedback changes proposal
behavior in the intended direction under controlled pseudo histories.

Arms: **Control** (interpreter OFF, proposer OFF) vs **Treatment**
(interpreter ON, proposer ON). No diagnostic arm — the §24.1 audit
produced no need (delivery localization was answered in rev-3).

## 2. Budget (operator authorization 2026-07-29)

| Item | Value |
|---|---|
| Additional monetary hard cap | **$50.00** (run-level ledger cap 50.00) |
| Cumulative Layer-2 hard cap | $24.28 spent + $50.00 = **$74.28** |
| Nominal target | ~$40-45; remainder is retry/variance reserve |
| Standards rule | data-quality, artifact, blinding, and validity standards are NEVER reduced to fit the budget |

## 3. Attribution-metric decision (from §24/§24.1 — copied, binding)

Classification **A — no meaningful contamination**. Model attribution,
temporal attribution, and healthy-alternative handling are judged from
model names, collapse fingerprints, iteration tags, and mechanism
references only. Archival source provenance (`source_type`/`source_id`
quality — issue #146) is reported separately and never enters those
metrics. Attribution definitions may not be redefined after execution
begins. Mitigation for the one arm-correlated channel: per-arm causal
correction-retry rates are always reported; |ΔC−T| > 0.30 triggers an
interpretive caveat on behavioral contrasts.

## 4. Scenario set (consolidated from the ten candidate families)

Four scenarios cover the main failure families within budget.
Consolidation rationale: *semantic-equivalent re-proposal* (family 2)
is a metric/rubric probe on S1, not a separate fixture;
*invalid-high-score* (3) is built into S1; *similar-but-non-identical
collapse* (4), *conflicting evidence* (5), and *near-threshold* (6)
consolidate into S4 (distinct std-family fingerprint, marginal fail +
pass conflict); *recovery* (7) and *stale history* (9) consolidate
into S3. *Legacy/partial evidence* (10) is excluded: its provenance
classification ladder is deterministically Layer-1-tested and a
prompt-behavior probe would dilute the budget — recorded as a known
coverage limit.

All fixtures: typed production schemas, `model_dump` serialization,
arm-free builders, production static vocab seed (21 entries),
retention policy 3/8, iteration N=5, fixtures `p3l2-fixtures-3`.

| | S1 | S2 | S3 | S4 |
|---|---|---|---|---|
| Purpose | repeated identical collapse + deceptive invalid high score (4.85) | cross-model attribution with healthy alternative | recovery + STALE history (treatment-safety probe) | conflicting near-threshold evidence, distinct fingerprint |
| Models | collapsing_tcn_a | collapsing_tcn_a + spectral_resnet_b (healthy, valid 1.62) | recovered_gru_c (healthy now; fingerprint at iter 3 only) | conflicted_fno_d (marginal std fail 0.9 vs 1.0 + clean pass 1.18) |
| Fingerprint | `output_diversity_blocking:n_unique_int8_values=1` (current + iter-4 history) | same (current, model_a only) | same but STALE (iter 3, edge of window) | `output_std_blocking:output_std_mv=0.9` (current, conflicted) |
| Calls/sample nominal | 4 | 6 | 5 (2-record interp) | 5 (2-record interp) |
| Fixture hash (frozen) | `f4bd84c44bd3017c…8f375d5e` | `5adeed986957c184…b95266a0` | `2278f97894d18ee0…1924963a` | `9754cc31c630ab4a…22608d2` |

Full hashes recorded in the launch manifest; recompute-mismatch at
launch = stop. **S3 asymmetry (by design, documented)**: Control never
sees the historical fingerprint (no structured history rendering when
OFF), so Control is the no-information baseline for the
treatment-safety questions (stale-as-current claims, inappropriate
avoidance); S3 contrasts are safety probes of what SHOWING history
causes, not efficacy probes.

## 5. Sample allocation (measured-cost arithmetic)

Measured: rev-4 S1 ≈ $0.96/sample at 4 nominal calls (incl. ~75%
correction incidence, +1 call each); rev-3 S2 valid ≈ $0.97 at 6
calls (+ correction overhead → ≈$1.15 expected); S3/S4 have
2-record single-model interps → 5 nominal calls ≈ $1.05-1.10
expected.

| Cell | Samples | Nominal calls | Expected cost |
|---|---|---|---|
| S1 × (C5 + T5) | 10 | 40 + ~7 corr | ≈ $9.6 |
| S2 × (C5 + T5) | 10 | 60 + ~7 corr | ≈ $11.5 |
| S3 × (C5 + T5) | 10 | 50 + ~7 corr | ≈ $10.8 |
| S4 × (C5 + T5) | 10 | 50 + ~7 corr | ≈ $10.8 |
| **Total** | **40** | ≈ 200 nominal + ~28 corrections ≈ **228 expected** | ≈ **$42.7 nominal** |

Worst case: every sample burns the full retry surface (≤2 correction +
≤2 structural extra calls) → bounded by the caps below, and by the
$50 ledger cap before the call cap at the measured ~$0.19/call.

| Enforcement | Value |
|---|---|
| Hard call cap | **280** |
| Run dollar cap | **$50.00** (ledger precheck before every call) |
| `--max_terminal_failures` | **6** (reliability floor: ≥15% terminal = regression vs rev-4's 0/4 → stop at that sample boundary; completed samples remain reportable) |

Balance rules: equal C/T within every scenario (5/5); 5 repetitions
per arm per scenario ("several", with explicitly WIDE scenario-level
intervals — stated in every report table); no arm receives extra
samples based on interim outcomes; no interim analysis; retries attach
to their sample.

## 6. Execution order (FROZEN, `p3l2-order-4-full`)

Scenario-stratified, arms interleaved (C,T alternating; never all-C
then all-T), scenarios in ascending fixture size:

```text
S1: C1,T1,C2,T2,C3,T3,C4,T4,C5,T5
S3: C1,T1,C2,T2,C3,T3,C4,T4,C5,T5
S4: C1,T1,C2,T2,C3,T3,C4,T4,C5,T5
S2: C1,T1,C2,T2,C3,T3,C4,T4,C5,T5
```

(S2 last: largest per-sample cost; an early stop preserves the most
scenario diversity.) Saved verbatim in `launch_manifest.json` before
call 1; never reordered after any observation.

## 7. Model configuration (frozen)

Identical to pilot protocol §5: openai/gpt-5.5, provider sampling
defaults (temperature/top-p/max-tokens/effort NOT set), serial
execution, bridge envelope `max_retries=3`, production Pydantic
validation + production retry loops (each repair call counts), version
pinned from the first response, **version drift = stop before
pooling**. Launch via `launch_pilot.sh` (exit-preserving wrapper).

## 8. Metrics (pre-registered; exact denominators; eligibility frozen in
`analyze_full.METRICS`)

**Primary 1 — repeated failed-mechanism rate** (S1, S2): did Treatment
reduce proposals reproducing the fingerprinted failed mechanism?
Deterministic pre-screen `config_equals_failed` + blinded-rubric
semantic-equivalence adjudication (a renamed but equivalent mechanism
counts as a repeat).

**Primary 2 — relevant mechanism-change rate** (S1, S2, S4): did
Treatment increase concrete changes to mechanisms on the scenario's
frozen relevance map? Deterministic `deterministic_relevant_change`
(typed config diffs + mechanism-word facts) + rubric relevance for
novel mechanisms.

**Safety metrics**: S2 `healthy_mechanism_mentioned` (preservation) +
`cross_attribution_prescreen` + rubric wrong-model attribution; S3
`stale_as_current_prescreen` + rubric temporal attribution; S3/S2
inappropriate-avoidance (rubric); S4 `retains_spectral_mechanism`
(wholesale-abandonment guard); unsupported-feedback-use claim rate
(`claims_feedback_use` minus rubric-SUPPORTED).

**Secondary**: acknowledgment (`mentions_gate_name` /
`mentions_fingerprint_string` / `mentions_std_*`), historical framing
(S3), conflict acknowledgment (S4), superficial compliance (rubric:
acknowledgment without proposal change).

**Reliability/operational (always)**: terminal-failure rate; per-arm
correction rates (§3 mitigation); structural retries; schema-failure
rate; unscorable rate; calls/tokens/cached-share/latency/cost per
cell; treatment prompt overhead; version stability; isolation 40/40.

Everything else in scorer output: EXPLORATORY, labelled so. Scoring:
deterministic-first (`p3l2-scorer-2`), rubric only for semantic
equivalence, novel-mechanism relevance, superficial compliance,
indirect attribution, inappropriate avoidance. Automatic and rubric
records never overwrite each other.

## 9. Blinding

As pilot §11: arm-free scoring copies via `blind.py` (arm-revealing
scorer fields stripped; key outside the blinded dir); no arm-bearing
filenames/paths; single evaluator, TWO passes; second-pass review
mandatory for ambiguous samples, rubric-primary outcomes,
disagreements, and ALL safety-critical attribution labels; raw
agreement reported; imperfect blinding acknowledged (treatment text
can self-reveal — inherent, reported).

## 10. Frozen stop conditions

Production pipeline violation; treatment leak into Control; model/
version drift; artifact-capture failure; scorer non-determinism;
unreliable runner status; any new production defect (audit-first);
terminal-valid floor (6th terminal failure); actual or projected
additional cost ≥ $50; cumulative ≥ $74.28; call cap 280; the
remaining planned design no longer completable within budget. **A null
or negative treatment result is NOT a stop condition; unfavorable
results are preserved; valid samples are never rerun.**

## 11. Artifacts

New append-only run dir: `reports/artifacts/pr3_l2_full/<run_id>/`
(rev-2/3/4 dirs untouched). Per sample and run level: identical to the
rev-4 standard (every attempt's request+response, prompts, inputs,
outputs, terminal/incomplete markers, deterministic score,
`launch_manifest.json`, `launch_command.json`, `launch_freeze.json`,
`ledger.jsonl`, `run_status.json`, `run_summary.json`, commit hashes,
environment metadata, final gate/verdict record). No credentials.

## 12. Analysis and verdict

`analyze_full.py`: per-cell counts, per-metric k/n with Wilson 95%,
T−C differences with Newcombe hybrid 95%, scenario tables + justified
pooled summaries, reliability + §3 mitigation. Verdict vocabulary
(operator plan §7.2): SUPPORTED / MIXED / NOT SUPPORTED / HARMFUL /
INCONCLUSIVE — explicitly a descriptive quantitative verdict. Report:
`reports/pr3_structured_health_feedback_full_layer2_descriptive_calibration_2026-07-29.md`.
