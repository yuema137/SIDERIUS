# V21 PR F — Inspection-cost scaling study (measure only): final report

**Date:** 2026-08-09 · **Host:** `ligroup` (lilab), CPU-only, loadavg
6.2–17.4 recorded per point · **Evidence:** `measurements_pilot.json` +
`measurements_pilot_rerun.json` (append-per-point JSONL, schema-validated
on write and read-back) · **Manifest hashes:** pilot `7bb4cb62…`, full
`805559bc…` · **Design ledger:**
`docs/design/v21_priorities/pr_f_inspection_cost_study.md`

## Scope — the operator-approved study population

> Full population-wide censoring prevalence was **not** measured because
> the calibrated cost is 10–30 h and PR F is not a V21 launch blocker.
> The pilot is sufficient to reject the simplistic "parameter count →
> inspection timeout" hypothesis and to motivate a separate targeted
> budget-policy study if a budget change is pursued.
> *(Operator decision, 2026-08-09 — the pilot + reproducibility rerun IS
> the formal F2b population, via the frozen wall-expiry rule's explicit
> subset-approval path.)*

Measured coverage: **3 of 12 pilot entries, 64 + 64 measurements across
two independent wall-bounded runs** (the 1800 s wall fired in both, by
design). The 107-entry full manifest remains frozen and hashed for any
future targeted study.

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

| evidence | run 1 | run 2 |
|---|---|---|
| direct candidate probe, B=64 (exact, post-hoc) | **149.97 s** | **145.42 s** |
| native `BatchSearchTimeout(operation="batch_candidate", B=64)` inside the real `resolve_inference_batch` (exact) | **145.05 s** | **141.41 s** |

This is the verbatim P3/V20 incident signature
(*"the bounded 'batch candidate' step at candidate batch 64"*), preserved
through the native `ProbeTimeoutRecord`. Timing dispersion ≈ 2.5 % on a
busy host.

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
| `A_stub_arch_001_a` | generated (stub) | 4,352 | 0.35 s | 0.9 s | 0.1 s |
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
CLEAR              26   (every timed repeat under its budget)
WOULD_BE_CENSORED   1   (the incident point: candidate_probe B=64,
                         4/4 exact observations over 120 s, zero straddle)
INDETERMINATE       0
illegal flips under union: 0   (27/27 verdicts stable across runs)
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
   historical candidates. The frozen 107-entry manifest and this harness
   are ready for exactly that.
3. **FU-F-1:** reconcile or retire the two inert declared budgets and the
   1200-vs-900 contradiction — a small cleanup PR of its own.

**No recommendation was implemented. No budget, probe, resolver, prompt
or production file was changed by PR F.**
