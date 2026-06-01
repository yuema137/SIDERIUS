# §10 End-to-end validation suite — run log

Dated record of every §10 validation-suite run. The suite specification
lives in [`external_agents_for_proposer.md` §10](external_agents_for_proposer.md#§10-end-to-end-validation-suite);
this file is its companion log, where each run produces one dated section.

The suite is a **permanent acceptance gate**, not a one-time checkpoint —
it re-runs across commits on the locked 7-paper corpus (§10.2) so results
are comparable over time. See `commit_plan_ml_literature_review.md` for
the schedule of expected runs:

| Trigger | Phase coverage | Source commit |
|---|---|---|
| §10 Phase 1 partial run | Phase 1 only (Step 1a + 1b) | Commit 2c-c (closes 2c) |
| First FULL run | Phases 1 + 2 | Commit 2d (closes Commit-2 family) |
| Prerequisite re-run | Phases 1 + 2 | Before Checkpoint D / Commit 6 |

## How to add a run

1. The pilot script (`tests/integration/nodes/test_ml_literature_review_phase1_pilot.py`)
   writes its rendered report to
   `reference_data/lit_review_pilot_cache/phase1_pilot_report.md`
   (gitignored). Future suite runs produce analogous artifacts via their
   own scripts.
2. Review the artifact against the §10.5 acceptance criteria.
3. Copy the artifact into a new dated section below, using the heading
   format `## YYYY-MM-DD — <run name>` (e.g.
   `## 2026-05-30 — §10 Phase 1 partial run`).
4. Add a short prose paragraph under the heading recording: which commit
   produced the artifact, which acceptance criteria were checked, which
   passed / failed, and the Checkpoint sign-off status (if applicable).
5. Commit the doc edit separately from any code change.

## Runs

*(none yet — first §10 Phase 1 partial run lands after Commit 2c-c.)*
