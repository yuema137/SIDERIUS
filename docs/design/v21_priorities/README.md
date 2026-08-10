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

**PR D is MERGED** (PR #189, merge commit `aace4abb`, 2026-08-08) — see
`pr_d_scientific_authority_reachable.md`. Its production diff is three
files and ten wiring lines: the authority declaration now reaches the tuner
input, whose two fields existed all along and were never populated. That
makes **all four launch-gating checkpoints satisfied**; PR E is the last
one before a V21 campaign can start.

PR D was the **fourth** consecutive instance of "a correct rule that
nothing calls", and it produced a new variant of that lesson — the same
shape appearing *inside the test suite* (`v21_priorities.md` §E.3d.9),
plus a correction on how multi-field absence failures must be
distinguished (§E.3d.10). Both bind E, F and G.

**PR E is MERGED** (PR #190, merge commit `f1f4c30a`, 2026-08-09) — the
V21 launch-blocking chain A → C → B → D → E is complete. Originally
implemented on
`feat/pr-e-proposal-scale-funnel` — `pr_e_proposal_scale_funnel.md` is the
live ledger. All operator decisions **O-E-1 … O-E-6** are frozen:
`candidate_id` is the only cross-stage transport (system-minted, never
LLM-supplied, observational join key only); measurements stay with their
native owners; the validator records BOTH parameter-count conventions
under unambiguous names; `stopped_at_stage` is derived on read; one
bounded pseudo-mode complete iteration is a merge requirement.

**PR F is MERGED** (PR #191, merge commit `fd7c8816`, 2026-08-10;
reviewed head `86355479`, CI green on that exact sha; zero production
diff — measure-only).
The pilot reproduced the V20 inspection timeout as an exact measurement
— six over-budget observations across two runs — and rejected the
"parameter count → timeout" story
(architecture-shaped cost: a 7 M deep WaveNet is censored at B=64 while
a 2.6 B FNO probes under budget). The full population sweep was
deliberately not run — the operator's MINIMUM-SUFFICIENT-EVIDENCE
correction replaced it with a bounded, timing-blind 8-entry stratified
subset (163 measurements, 54 CLEAR / 1 INDETERMINATE): the builtin
WaveNet width ladder scales cleanly ~2× per channel-doubling
(15 → 28 → 56 s at B=64) while the 30-layer cousin is censored at 7 M
params — **depth, not width or parameter count, crosses the budget** —
and every other sampled realized family (unet 87 M, fourier/pyramid,
rnn/gru) clears with wide margins. The subset also surfaced **F-A4, a
third censoring mechanism: host memory** — a 1 M-param selective-SSM at
B=64 × seg 40,000 drove the in-process probe to 47 GB RSS and a kernel
OOM kill (the documented 2026-07-31 host-takedown class that
production's isolated worker contains). Deliverable in
`reports/v21_pr_f_inspection_cost/report.md`.
Rev 3 matched the harness's timeout handling to production's
per-operation enforcement (the native 180 s preemptive training-probe
alarm is preserved, never relaxed to 2×), preserves native
`BatchSearchTimeout` records verbatim in a study envelope, froze
wall-expiry-is-not-completion, the timing-blind grid rule, and the
no-pooled-causal-slope interpretation boundary.
The complete budget-consumer census found TWO of the five budgets are
INERT (`single_inspection_seconds` enforced nowhere;
`preflight_total_seconds=1200` unconsumed while the real end-to-end
bound is a hardcoded 900 s subprocess deadline) — filed as FU-F-1, not
fixed. The incident budgets are POST-HOC, so overruns yield EXACT times
and true censoring only occurs at the harness's 2× SIGALRM — which
reuses production's own primitive. Execution is wall-bounded (30-min
pilot wall, ramped), not estimate-bounded: the honest theoretical worst
case is ~2 700 s per entry per repeat. Zero production diff; CPU-only.

**PR G is design-FROZEN (operator-approved 2026-08-10) and its
implementation is IN PROGRESS** on
`feat/pr-g-capability-derived-inference-batch`; its doc is the live
implementation ledger. It carries an update block derived
from what A/B/C actually proved — see `v21_priorities.md` §E.3d, which is
binding on all of them. The single most reusable finding: three PRs in a
row found **a correct rule that nothing called**, so every remaining PR
must first ask whether the mechanism it wants already exists and lies
inert. PR G is the one most changed by this — the measured memory profile
it wants may already be reaching the policy.

Open follow-ups: **FU-A-1/2/3**, **FU-B-1/2/3/4**, **FU-D21-1/2** and the
PR-C-era items in §E.3b. None blocks E-G. Note the `FU-D21-*` prefix: V20's
PR D already owns `FU-D-1` … `FU-D-12`, two of which are live
operator-facing flags. **FU-B-4** (live formal confirmation of the S3
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
| **D** | [`pr_d_scientific_authority_reachable.md`](./pr_d_scientific_authority_reachable.md) | V21 launch blocker | **MERGED** — PR #189, `aace4abb` |
| **E** | [`pr_e_proposal_scale_funnel.md`](./pr_e_proposal_scale_funnel.md) | Before first V21 data | **MERGED** — PR #190, `f1f4c30a` |
| **F** | [`pr_f_inspection_cost_study.md`](./pr_f_inspection_cost_study.md) | Blocks only a budget change | **MERGED** — PR #191, `fd7c8816` (measure-only) |
| **G** | [`pr_g_capability_derived_inference_batch.md`](./pr_g_capability_derived_inference_batch.md) | Non-blocking | **IN PROGRESS** — design FROZEN 2026-08-10; implementing on `feat/pr-g-capability-derived-inference-batch` |

Recommended serialization: **A → C → B → D → E**, then F, then G.

### PR D re-scoped 2026-08-08 — read §E.3e before designing it

A code-and-artifact audit **withdrew PR D's original causal premise**. The
per-file evidence PR D was meant to add is **already live**: per-file
`Weight %` has reached the planner and reflector prompts since
`5c8f76c4` (2026-05-01), and the very record the ledger cited
(`iter_006_001`) carries it — the agent named the file-19 "over-focus
risk" itself. So *"per-file evidence was not shown"* is **false** and
*"the scalar misled the reflector"* is **not supported**.

PR D is re-scoped around the defect that *is* active and launch-blocking:

> No formal record produced through any current SIDERIUS launcher can
> become authoritative, because every production launcher omits
> `healthgate_mode` / `result_authority` when constructing or invoking the
> tuner. The mechanism is live and correct; only the hand-invoked tuner
> CLI supplies it.

Same shape as A/B/C (§E.3d.1) for the fourth time. Consequences are
decision-bearing: the record cannot become the chain incumbent
(`core/resume.py:678`) and is excluded from the scientific aggregate
(`result_interpretation_agent.py:1052`).

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
