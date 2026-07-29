# V19 PR-Specific Design Documents

Per-PR design documents for the V19 ladder, as required by the locked
planning baseline [`../v19_priorities.md`](../v19_priorities.md)
(see its Planning-lock "content division": the baseline holds the
roadmap and progress state; code audits, architecture, exact
interfaces, commit plans, detailed tests, scenario selection,
sample-size reasoning, Gate commands, cost estimates, stop-and-show
evidence, and implementation logs live here).

## Index

| PR | Design doc | Status |
|----|-----------|--------|
### Required V19 work

| PR | Design doc | Status |
|----|-----------|--------|
| PR 1 — Chain-level incumbents | [`pr1_chain_incumbents.md`](./pr1_chain_incumbents.md) | complete — merged (PR #137) |
| PR 2 — Data ordering as an optimization dimension | [`pr2_data_ordering.md`](./pr2_data_ordering.md) | rev 3 locked; implementation complete, PR open |
| PR 3 — Structured HealthGate feedback propagation | — | not started |

### Parallel operational work

| Item | Design doc | Status |
|----|-----------|--------|
| O1a — Runtime provenance | — | not started |
| O2 — `--only` launcher selector | — | not started |

### Unscheduled candidate features

Threshold recalibration, adaptive routing, metric redesign, stateful
stop policies, and workflow evolution are NOT required for V19
completion and have no per-PR design docs. They live as unscheduled
candidates in [`../candidate_features_v19.md`](../candidate_features_v19.md)
and may be promoted only by an explicit operator decision.

Naming convention: `pr{N}_{short_slug}.md` (e.g. `pr1_chain_incumbents.md`,
`o2_launcher_only_selector.md`).

Each document must complete the design and validation template defined
in the baseline's §2.0 "Per-PR exit contracts" and carry the
corresponding progress-checkpoint evidence.
