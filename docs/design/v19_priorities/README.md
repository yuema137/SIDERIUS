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
| PR 1 — Chain-level incumbents | [`pr1_chain_incumbents.md`](./pr1_chain_incumbents.md) | rev 3 — P1-D approved, locked; implementation starting |
| PR 2 — Data ordering as an optimization dimension | — | not started |
| PR 3 — Structured HealthGate feedback propagation | — | not started |
| PR 4a — Threshold & aggregation study | — | not started |
| PR 4b — Adaptive routing + fingerprint avoidance | — | not started |
| PR 5 — Metric integrity & score-variant analysis | — | not started |
| PR 6 — Stateful stop policies | — | not started |
| PR 7+ — Workflow evolution (per sub-PR docs) | — | not started |
| O1a — Runtime provenance | — | not started |
| O2 — `--only` launcher selector | — | not started |

Naming convention: `pr{N}_{short_slug}.md` (e.g. `pr1_chain_incumbents.md`,
`pr4a_threshold_study.md`, `o2_launcher_only_selector.md`).

Each document must complete the design and validation template defined
in the baseline's §2.0 "Per-PR exit contracts" and carry the
corresponding progress-checkpoint evidence.
