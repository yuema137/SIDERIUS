# V21 PR F — Inspection-cost scaling study (measure only): final report

**Date:** 2026-08-09 · **Host:** `ligroup` (lilab), CPU-only, loadavg
6.2–17.4 recorded per point · **Evidence:** `measurements_pilot.json` +
`measurements_pilot_rerun.json` + `measurements_subset.json` +
`measurements_subset_b.json` (append-per-point JSONL, schema-validated
on write and read-back) · **Manifest hashes:** pilot `7bb4cb62…`, full
`805559bc…`, subset `1ccc46b0…` (subset_b carries its standalone
single-entry sub-manifest hash `0834abda…`) · **Design ledger:**
`docs/design/v21_priorities/pr_f_inspection_cost_study.md`

## Scope — the operator-approved study population

> Full population-wide censoring prevalence was **not** measured because
> the calibrated cost is 10–30 h and PR F is not a V21 launch blocker.
> The pilot is sufficient to reject the simplistic "parameter count →
> inspection timeout" hypothesis and to motivate a separate targeted
> budget-policy study if a budget change is pursued.
> *(Operator decision, 2026-08-09 — the pilot + reproducibility rerun IS
> the formal F2b population, via the frozen wall-expiry rule's explicit
> subset-approval path. Subsequently amended by the operator's
> MINIMUM-SUFFICIENT-EVIDENCE correction, which added the bounded
> stratified subset — see "The bounded F2b subset" below.)*

Measured coverage: **3 of 12 pilot entries, 64 + 64 measurements across
two independent wall-bounded runs** (the 1800 s wall fired in both, by
design). The full manifest (112 entries, of which 107 are measurable —
5 builtin ladder steps are `invalid_config`) remains frozen and hashed
for any future targeted study.

## The budgets under study (from the consumer census — only the ENFORCED ones)

```text
single_candidate_seconds = 120   POST-HOC   (batch_resolver.py:201)
batch_search_seconds     = 600   POST-HOC   (batch_resolver.py:157)
single_probe_seconds     = 180   PREEMPTIVE (wrapper.py:591, SIGALRM)
```

`single_inspection_seconds=120` and `preflight_total_seconds=1200` are
**declared but enforced nowhere** (findings F-A1/F-A2 below) and are
deliberately not measured against.

## Headline result — the V20 incident is a reproducible measurement

`wavenet_30layer_baseline` — population `v20_generated_realized`,
architecture family *deep dilated WaveNet*, **7,089,024** total params
(= trainable), seg 16,000:

| evidence | run 1 (repeats 0, 1) | run 2 (repeats 0, 1) |
|---|---|---|
| direct candidate probe, B=64 (exact, post-hoc) | **149.97 s / 145.42 s** | **147.29 s / 143.21 s** |
| native `BatchSearchTimeout(operation="batch_candidate", B=64)` inside the real `resolve_inference_batch` (exact) | **145.05 s** | **141.41 s** |

This is the verbatim P3/V20 incident signature
(*"the bounded 'batch candidate' step at candidate batch 64"*), preserved
through the native `ProbeTimeoutRecord`. All six exact observations sit
19–25 % over the 120 s budget; timing dispersion across them is ≈ 2–5 %
on a busy host.

**The per-batch cost curve is linear in B** (run 1, exact seconds):

```text
B:        1      2      4      8      16     32     64
elapsed:  1.35   3.38   9.83   21.67  41.97  80.28  149.97
≈ 2.34 s per batch unit  →  the 120 s post-hoc budget censors this
architecture at B ≳ 51
```

## The architecture-vs-size contrast

| entry | family | total params | B=64 probe | full search | training probe |
|---|---|---|---|---|---|
| `A_stub_arch_001_a` | generated (stub) | 4,352 | 1.0 s | 1.8 s | 0.14 s |
| `A_wavenet_30layer_baseline` | generated (deep dilated) | 7,089,024 | **149.97 s — OVER budget** | ended by the native candidate timeout | 2.0 s |
| `B_019_gated_fno` (×8 ladder) | gated_fno | **2,621,834,112** | 57–62 s — *under* budget | **completed** in ~205 s with a **measured** no-feasible-batch verdict (predicted 21.5 GB @ B=1 vs the 12 GB cap, vram-binding) | 25.9 s |

**A 7 M-parameter model is censored while a 2,600 M-parameter model is
not.** Pointwise, inspection cost is **architecture-shaped, not
size-shaped** — the deep dilated stack's per-layer forward dominates,
while the enormous FNO probes cheaply and is then correctly refused on
*measured VRAM feasibility*, which is exactly the kind of verdict the
honest-absence contract permits (a measurement, not a timeout).

Per the frozen interpretation boundary: this is a **pointwise** claim
from labelled entries. No pooled cross-architecture slope is fitted
anywhere in this study, and no causal "size → cost" law is asserted;
within-family ladder evidence would require the deferred targeted study.

## Classification (frozen rule; union of both runs, 27 operation points)

```text
pilot (union of two runs, 27 points):
  CLEAR 26 · WOULD_BE_CENSORED 1 (the incident point, 4/4 exact over) ·
  INDETERMINATE 0 · illegal flips 0
bounded subset (55 points):
  CLEAR 54 · WOULD_BE_CENSORED 0 · INDETERMINATE 1 (the F-A4 OOM point)
```

Note on the incident entry's `full_search` row: it classifies CLEAR
against the search's *own* 600 s budget — because the search was ended at
~145 s by the **candidate** budget, whose native record names the true
censor. The disposition column, not the search-budget verdict, carries
that story; reading only the CLEAR count would miss it, which is why
dispositions and verdicts are reported together.

Disposition accounting over the approved (operator-scoped) population:
`126 completed(exact) + 2 native_timeout(exact) + 0 backstop + 0
deadline + 0 unloadable + 0 invalid_config = 128 measurements` — closes
exactly. Wall markers present in both files (the walls fired; the
operator then approved the measured coverage as the formal population).

## P6.3 overlay (ledger-recorded values only)

The pilot deliberately included the population-A entries nearest each
recorded P6.3 value (663,488 · 7,280,256 · 8,409,280 · 12,772,096); the
wall permitted measuring the incident-class member (7,089,024 — nearest
the 7,280,256 anchor). Its verdict: **censored at B=64, clear at
B ≤ 32**. The remaining anchors are covered by the frozen manifest for
any future targeted study; no distribution claim is made from one point
(§E.3d.6).

## The bounded F2b subset (operator-corrected scope: minimum sufficient evidence)

> *"Validation cost must be proportional to the information needed for
> the decision; exhaustive coverage is not itself an acceptance
> criterion."* — operator, 2026-08-09. The full 113-entry sweep was
> deliberately not run; this frozen, timing-blind, 8-entry subset
> (`select_f2b_subset`, hash `1ccc46b0…`) closes the two remaining
> decision-relevant uncertainties: the within-family ladder for the
> incident family, and family breadth in the realized population.

**Evidence:** `measurements_subset.json` (136) + `measurements_subset_b.json`
(27) = 163 measurements; 55 operation points; verdicts under the frozen
rule: **54 CLEAR / 0 WOULD_BE_CENSORED / 1 INDETERMINATE** (the OOM point
below).

### The within-family ladder — the causal size question, answered for 3 steps

Built-in WaveNet, identical family, channels doubled per step, R=3
(medians, exact):

```text
step   params      B=64 probe   full search   training probe
x0.5     81,632     15.3 s        26 s          0.3 s
x1      302,784     27.6 s        50 s          0.4 s
x2    1,176,704     55.8 s       100 s          0.9 s
ratio/step:          ~1.8-2.0x    ~1.9-2.0x     smooth, monotone
```

Within this family, cost scales cleanly (~2× per channel-doubling) —
extrapolating ONE more step (stated extrapolation, NOT a measurement)
puts the ×4 step at B=64 ≈ 110 s, *just under* the 120 s budget, while
the **30-layer** generated cousin measured 150 s at only 7 M params:
**within the WaveNet family, depth crosses the budget before width
does.** The ×4 step was deliberately NOT probed (host-safety, below);
the ×8 step is schema-invalid.

### Family breadth — censoring is confined, but a THIRD mechanism appeared

| family (population A rep) | params | seg | B=64 probe | verdict |
|---|---|---|---|---|
| unet (`spectral_bottleneck_unet_ce_control`, the largest generated entry) | 86,944,928 | 8,000 | 17.2 s | CLEAR everywhere |
| fourier/pyramid (`tiny_multirate_spectral_pyramid_classifier`) | 159,000 | 40,000 | 9.4 s | CLEAR everywhere |
| rnn/gru (`embedded_resconv_bigru_head_compact`) | 162,112 | 625 | 0.24 s | CLEAR everywhere |
| ssm/mamba (`light_selective_ssm_skip_classifier`) | 1,027,248 | 40,000 | — | **kernel OOM-killed the study process at 47 GB anon-RSS** |

**Finding F-A4 — a third censoring mechanism: host memory, not time.**
Probing the 1 M-param selective-SSM at B=64 × seg 40,000 in-process drove
anon-RSS to 47,010,964 kB and the kernel OOM-killer killed the study
(dmesg 2026-08-09 15:39:12) — the exact documented 2026-07-31
host-takedown class that `isolated_probe.py`'s worker subprocess exists
to contain. Recorded as `harness_deadline` per the frozen rule (no
elapsed time fabricated; 135 prior measurements survived via
append-per-point). The file's final line is, verbatim,
`{"wall_expired": {"note": "run killed by kernel OOM, not the wall;
135 prior measurements intact"}}` — the format's only interruption
marker is the `wall_expired` key, so `read_measurements` reports
`wall_expired=True` for this file; the stored note carries the actual
cause, and nothing in the artifact claims the 3600 s wall fired.
Two consequences: (1) the study's in-process
direct-probe axis inherits the risk production already solved with the
isolated worker — a harness limitation now stated from evidence, not
theory; (2) for budget policy, TIME budgets are not the only inspection
censor: some architectures are host-memory hazards at high batch before
any timer matters, and the production worker's RSS sampling is the live
defence.

### Coverage and non-claims

Measured: 6 of 8 subset entries complete (162 exact measurements +
1 OOM `harness_deadline`). NOT measured, with reasons: the ×4 WaveNet
ladder step (declined for host safety after the OOM — activation
footprint projected ≈2× the ×2 step at B=64 × seg 40,000; the stated
extrapolation above carries the information at zero risk) and the SSM
beyond its first probe. **This evidence supports:** rejecting a global
size-based budget policy; a clean within-family width ladder for 3 steps;
depth-vs-width for the incident family; family-confinement of
time-censoring among the sampled families; the existence of the
host-memory mechanism. **It cannot support:** population-wide censoring
prevalence or per-family censoring rates over the 83 historical
candidates — the exhaustive sweep was deliberately not run.

## Hardware-local calibration boundary (operator clarification, 2026-08-09)

PR F does NOT identify a universal inspection-time threshold.

The wall-time measurements in this study calibrate the CURRENT
inspection policy on the specific execution environment used for the
study: the current host/CPU (`ligroup`, CPU-only, recorded loadavg per
point), the current runtime/software stack, the observed host-load
conditions, and the current production implementation of the inspected
operations. Therefore a result such as `candidate probe > 120 s` means:
**under this execution environment, the current 120-second policy would
censor this operation.** It does NOT mean 120 seconds is the correct or
incorrect universal threshold for every SIDERIUS deployment. Absolute
inspection time is deployment-sensitive: a materially different
machine/runtime may change the observed wall-time scale even when the
candidate architecture and configuration are identical.

### Consequence for portability

A new deployment/hardware environment should perform a bounded
calibration before treating the current absolute timing thresholds as
calibrated. This does NOT imply rerunning the complete PR F study — a
future calibration procedure should use the minimum sufficient set of
representative operations/architectures needed to characterize the
local runtime regime.

### Long-term design implication

The preferred long-term direction is NOT to replace 120 seconds with
another global magic constant. Recorded as a recommendation for future
work: inspection budgets should ideally become deployment-aware and
potentially dynamic, e.g.

```text
hardware/runtime calibration
  -> local timing baseline
  -> operation-aware and/or architecture-aware budget
  -> staged/adaptive inspection where justified
```

The exact future mechanism is NOT decided by PR F. Possible future
approaches — hardware-profile-specific defaults; startup calibration;
normalized timing relative to local reference probes;
architecture/operation-aware limits; staged or adaptive inspection —
must be evaluated in a separate design/change PR. PR F remains
measure-only and implements NONE of these policies.

### Claim boundary

**SUPPORTED by this study:** the behavior of the current policy on the
measured execution environment; architecture-specific examples of
censoring/non-censoring; evidence that raw parameter count alone is not
a sufficient timing proxy.

**NOT SUPPORTED:** a universal optimal timeout; portability of the
measured absolute wall times to different hardware; a globally valid
mapping from parameter count to inspection cost; the exact design of a
future dynamic budget policy.

## Findings (observations, not tasks — FU-F-1)

- **F-A1:** `single_inspection_seconds=120` is declared but enforced
  nowhere (its only reference builds a tracing-failure record with
  `elapsed=0.0`).
- **F-A2:** `preflight_total_seconds=1200` has zero consumers; the real
  end-to-end bound is a **hardcoded 900 s** subprocess deadline
  (`isolated_probe.py:441`, `preflight_adapter.py:222`) — declared 1200
  vs enforced 900, unnoticed because the declared value is never read.
- **F-A3:** torchinfo launders in-hook exceptions into
  `RuntimeError("Failed to run torchinfo…")`; a SIGALRM survives only as
  `__cause__`. The study harness chain-walks; production's wrapper
  handles it via its `"torchinfo" in str(e)` branch, which files a
  laundered native training alarm as a `model_inspection` tracing
  failure.

None of these were fixed here — PR F is measure-only.

## Recommendation (changes nothing; for a separate PR, if pursued)

1. **Do not raise `single_candidate_seconds` globally** (e.g. 120 → 300).
   The pilot's own evidence argues against it: cost is
   architecture-shaped, and a global raise would spend up to 2.5× longer
   on every pathological candidate while the actually-censored class
   (deep dilated stacks at B=64) is better served by structural options —
   **staged inspection (probe small batches first and extrapolate the
   measured-linear curve), a cheaper analytic pre-flight for known-linear
   families, or an architecture-aware budget.**
2. **If a budget change is pursued, run the targeted per-family ladder
   study first** (WaveNet × depth, PUNet × depth, Transformer × layers …)
   — a few dozen strategically chosen points answer the causal question
   with more information density than mechanically sweeping the 83
   historical candidates. The frozen manifest (112 entries, 107
   measurable) and this harness are ready for exactly that.
3. **The host-memory mechanism (F-A4) belongs in any budget redesign:**
   the isolated worker's RSS containment is already the production
   defence; a future inspection policy should treat "probe would exhaust
   host RAM" as a first-class *measured* refusal alongside time budgets —
   never as a timeout, and never by probing large batches in-process.
4. **Absolute thresholds do not transfer across hardware.** If SIDERIUS
   is deployed on materially different hardware/runtime, repeat the
   inspection-time calibration with a small bounded calibration suite
   (minimum sufficient representative operations/architectures — see
   the hardware-local calibration boundary above) rather than assuming
   the current absolute thresholds transfer unchanged.
5. **FU-F-1:** reconcile or retire the two inert declared budgets and the
   1200-vs-900 contradiction — a small cleanup PR of its own.

## Errata — 2026-08-09 evidence audit (prose corrected to match evidence)

A read-only audit re-derived every quoted number from the measurement
files while the terminal test suite ran. Five prose defects were found —
**the measurement evidence itself was internally consistent throughout**;
in each case the artifact is authoritative and the text was corrected to
follow it. Original statements are preserved here.

1. **Headline table run-labels.** Was: probe B=64 "run 1: 149.97 s /
   run 2: 145.42 s". Evidence: each pilot file holds TWO probe repeats —
   run 1: 149.97/145.42 (repeats 0/1), run 2: 147.29/143.21. 145.42 was
   run 1's second repeat, not run 2. Corrected table shows all four; the
   incident count rises from "three times" to SIX over-budget
   observations (4 exact probes + 2 native timeouts).
2. **Stub row.** Was: 0.35 s probe / 0.9 s search / 0.1 s training —
   drafting-time values. Evidence (run 1, medians): ≈1.0 s / ≈1.8 s /
   ≈0.14 s. Still ≪ every budget; the contrast claim is unaffected.
3. **Ladder ×2 step.** Was 56.0 s at B=64. Evidence repeats
   55.66/55.76/56.64 → median 55.76 → 55.8 s; probe ratio/step is
   1.8–2.0×.
4. **bigru cell.** Was 0.25 s. Evidence 0.28/0.23/0.24 → median 0.24 s.
5. **Manifest cardinality.** "107-entry full manifest" clarified: the
   frozen manifest holds 112 entries, of which 107 are measurable
   (5 builtin ladder steps are `invalid_config`).

No measurement JSON, manifest, script, test or production file was
changed to make documentation agree — the prose followed the evidence.

**No recommendation was implemented. No budget, probe, resolver, prompt
or production file was changed by PR F.**
