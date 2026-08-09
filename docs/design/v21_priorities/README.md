# V21 Priorities — per-PR design documents

The authoritative plan is `docs/design/v21_priorities.md`. That document
records what running V20 exposed (Part I), the operator's research
direction (Part II), and the scope of each PR (Part III). **This folder
is where each PR's actual audit findings, design decisions and commit
plan live.**

Per the operator rule carried forward from `v20_priorities.md` §20.1:
every PR gets a design document here, and **no implementation begins
until the operator has reviewed and approved it.** Part III is
deliberately scope-level; the audits it requires routinely change the
design, so a PR must not be implemented from Part III alone.

## Status

Plan approved in principle 2026-08-07, with six design corrections
applied. **All three V21 launch blockers are MERGED:** PR A (#186,
`b9f88ae5`), PR C (#187, `cac86c94`) and PR B (#188, `0aae3f4b`), all
operator-merged with CI green.

```text
PR A   the agent can propose AND execute different scientific formulations
PR C   a generated model is a production first-class citizen
PR B   resource prediction / admission / realization / attribution have
       one clear and consistent semantics
```

**Q-B-1 is FROZEN as S3** (operator, 2026-08-08) and now governs every
consumer of `vram_budget_gb`, not only PR B — recorded in
`v21_priorities.md` §E.3c.

**PRs D-G are not started, and each now carries an update block** derived
from what A/B/C actually proved — see `v21_priorities.md` §E.4, which is
binding on all of them. The single most reusable finding: three PRs in a
row found **a correct rule that nothing called**, so every remaining PR
must first ask whether the mechanism it wants already exists and lies
inert. PR G is the one most changed by this — the measured memory profile
it wants may already be reaching the policy.

Open follow-ups: **FU-A-1/2/3**, **FU-B-1/2/3/4**, and the PR-C-era items
in §E.3b. None blocks D-G. **FU-B-4** (live formal confirmation of the S3
surface) is due before the first full V21 production campaign.

### Scope correction recorded 2026-08-07

PR A was originally scoped as "build a capability-based output/loss
compatibility contract". Code audit during design showed **that contract
already exists and is live**
(`ExperimentConfig.validate_architecture_loss_match`), and that the
originally cited blocker (`LossConfig.check_compatibility`, a
`model_type != "fcnet"` literal) has **zero production callers**. The
real blockers are upstream — the implementor cannot emit regressor
metadata and the validator cannot accept it. PR A is therefore
**smaller**: make the existing contract reachable. Full correction in
`v21_priorities.md` Part I §P1.

Two consequences for other PRs:

- **PR C** additionally owns `get_output_type`'s silent
  `unknown → "classifier"` fallback, and owns restoring **formal
  promotion** with a deterministic generated-model fixture through a
  clean measurement worker. **Refined by PR C's own audit
  (2026-08-08):** the *tail* of that chain — measurement → admission →
  formal → record — was already demonstrated by PR A's Gate 2C; the
  untested segment is the *head*, `valid trial → winner → formal`,
  because Gate 2C reached formal with **no HealthGate-valid trial
  winner** — formal ran on the planner's unvalidated plan. See the PR C
  doc §0.1 (which also corrects a misreading: `[FORMAL OVERRIDE]` prints
  on the *healthy* path too, so only its `WARNING` variant is the
  pathology). **Resolved by O-C-1**, and delivered: the head is proven
  deterministically by C5a, the tail live by PR A (classifier) and C5b
  (regressor).
- **PR A does not fix formal promotion.** It makes regression
  *expressible*; PR C makes a generated model *executable* across the
  process boundary.

| PR | Document | Gate | Status |
|---|---|---|---|
| **A** | [`pr_a_reachable_output_contract.md`](./pr_a_reachable_output_contract.md) | V21 launch blocker | **MERGED** — PR #186, `b9f88ae5` |
| **B** | [`pr_b_resource_budget_semantics.md`](./pr_b_resource_budget_semantics.md) | V21 launch blocker | **MERGED** — PR #188, `0aae3f4b`; Q-B-1 frozen as S3 |
| **C** | [`pr_c_generated_model_production_compat.md`](./pr_c_generated_model_production_compat.md) | V21 launch blocker | **MERGED** — PR #187, `cac86c94` |
| **D** | `pr_d_per_file_evidence.md` | Before V21 | not started |
| **E** | `pr_e_scale_funnel_instrumentation.md` | Before first V21 data | not started |
| **F** | `pr_f_inspection_cost_study.md` | Blocks only a budget change | not started |
| **G** | `pr_g_capability_derived_inference_batch.md` | Non-blocking | not started |

Recommended serialization: **A → C → B → D → E**, then F, then G.

## Binding principles every document in this folder inherits

From Part III §E.2, in force for all seven PRs:

1. **Gradual genericization** (`v20_priorities.md` §1.4) — in-passing
   refactoring toward the generic design, never a big-bang rewrite. The
   standing review question: *does the code this change touches still
   treat TIDMAD, the current task, or the current machine as the
   framework itself?*
2. **Complete transport contract** — every capability crossing a schema,
   artifact, CLI, environment or subprocess boundary declares and tests
   its full chain. **Parent-process reachability is never evidence of
   subprocess reachability.** A transport test must fail when any single
   hop is removed, and a child must never satisfy a test using a registry
   inherited from the parent.
3. **The metric is frozen** — no PR may change the score formula,
   aggregation, normalization, anchoring or weighting. A result that
   looks strange is audited for *how it was produced*.

Plus the V20 inheritance: minimal change, one causal problem per PR,
evidence before expansion, and the reachability requirement.

## Acceptance is never "CI green"

SIDERIUS's configured full CI is **unit + static by design** — `ruff
check`, `ruff format --check`, `pyright`, and `pytest tests/unit/ -m "not
real_run"`. It proves nothing about any production seam. Every PR's
acceptance is:

```text
configured full CI green
  +
that PR's targeted production-reachability / transport tests green
  +
that PR's bounded real validation, where Part III requires one
```

## Document template

Each document carries the `v20_priorities.md` §20.11 template filled in,
plus the five V21-specific lines from Part III §E.7:

```text
Metric-frozen proof:
Name-keyed dependency added:
Transport contract:
Subprocess evidence:
Acceptance evidence:
```

It must also contain the required pre-implementation audit **already
performed and evidence-cited**, the commit plan, the checkpoints, and the
validation plan. This mirrors the V19 and V20 workflows, which caught
scope and factual errors in review rather than in code.
