# V18 Priority Decisions

- **Status**: CLOSED (2026-07-24) — V18 pivoted from the drafted
  workflow-adaptation release to a split-mode + runtime-control release
  after the Wave-1 runtime incident. Unimplemented draft items moved to
  [`v19_priorities.md`](./v19_priorities.md) (operator decision,
  2026-07-24; tracked in issue #136 for the runtime-control follow-ups).
- **Scope (as delivered)**: split-scope exploration campaign +
  calibrated runtime estimation and enforcement
- **Related**: [`v17_priorities.md`](./v17_priorities.md),
  [`v19_priorities.md`](./v19_priorities.md),
  [`runtime_estimation_and_watchdog.md`](./runtime_estimation_and_watchdog.md),
  [`enable_partial_file_list.md`](./enable_partial_file_list.md)

## 1. Original goal vs. actual delivery

The draft asked: "Can SIDERIUS use V17's structured health information
to adapt its future proposals and workflow decisions?" That agenda is
now V19's. What V18 actually delivered:

| Delivered | Where |
|---|---|
| DataScope — partial-file-list runs, run-invariants lock, split-mode tooling (DS1-DS8) | PR #130; `enable_partial_file_list.md` |
| Seedless cold-start chains | PR #126 |
| Server-independent scoring reference + H100 portability | PRs #125, #127 |
| HealthGate-valid candidate selection + persisted formal thresholds | PR #124 |
| Runtime-control system (RT1–RT6, Gates 1–2) + V18r relaunch: exact workload resolution, in-subprocess measured verification, observation store + priors, fail-closed admission, watchdog, guardrails | PR #135; `runtime_estimation_and_watchdog.md` |
| Trial/formal safety-factor split (trial 2.0 / formal 1.5) after the Wave-1A drift diagnostic | commit `43212fe`; design doc §12 Wave-1A entry |
| V18r split-mode campaign (8 chains, 4 scopes, waves 1A/1B/2) | `reports/v18_20260724.md` (operational runbook, local) |

## 2. Disposition of the drafted capability groups

| Draft group | Outcome |
|---|---|
| 3.1 Feedback propagation | **Partial.** Condensed health-validity propagation landed (`best_raw_health_validity`, `per_model_raw_best_health_validity` — PR #124). Per-round structured gate fields (`is_degenerate`/`failure_reason`/`gate_action` in `ModelRunSummary` + the tune→interp protocol) and the prompt-template consumption did NOT land → V19 §2.1. |
| 3.2 Adaptation | **Not implemented** (V18r runs the frozen observe-mode policy) → V19 §2.2, now with V17 + legacy-V18 + V18r evidence. |
| 3.3 Independent stateful stop policies | **Not implemented** → V19 §2.3 (carried verbatim). |
| 3.4 Chain-wide best valid formal incumbent | **Not implemented** — confirmed still-live in V18r production 2026-07-24 (`current_run_best_formal_score` fixed at 0.0 per iteration across the subprocess boundary) → V19 §2.4, issue #136. |
| 3.5 Workflow evolution | **Not implemented** → V19 §2.5. |
| 3.6 Metric refinement | **Partial.** The correlation guard shipped in modified form as the `pearson_dispersion_recording` HealthGate check (M8 §3.4), not inside `score_vector`. Remainder (in-scorer integrity gate decision, score-formula variants) → V19 §2.6. |
| 3.7 Forensic backlog (v15 5.5763 outlier revisit) | **Not implemented** (the class-127 fingerprint mechanism itself is documented in `pluggable_health_checks.md` §7.1) → V19 §2.7. |
| §4 DEFER-tier reclassification table | Carried to V19 §2.8 unchanged. |

## 3. Why the pivot

The 2026-07-23 Wave-1 launch exposed the runtime-estimation failure
class (a formal attempt admitted at 2.00 ms/step static estimate that
ran at 44.3 ms/step — ~5.9 h vs a 120-min budget, unenforced). Making
the campaign runnable at all took precedence over the adaptation
agenda: the RT series, its gates, and the V18r relaunch consumed the
release. See `runtime_estimation_and_watchdog.md` (motivation + §12
evidence) and `reports/v18_20260723.md` (legacy runbook, superseded).

## 4. Related docs

- [`v19_priorities.md`](./v19_priorities.md) — where the adaptation
  agenda now lives
- [`v17_priorities.md`](./v17_priorities.md) — the substrate V19 builds on
- [`runtime_estimation_and_watchdog.md`](./runtime_estimation_and_watchdog.md)
- [`enable_partial_file_list.md`](./enable_partial_file_list.md)
- [`pluggable_health_checks.md`](./pluggable_health_checks.md)
