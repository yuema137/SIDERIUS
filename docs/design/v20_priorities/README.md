# V20 Priorities — per-PR design documents

The authoritative plan is `docs/design/v20_priorities.md`. That document
records what V19 exposed, what V20 must fix, and the scope of each PR
(§20). **This folder is where each PR's actual audit findings, design
decisions and commit plan live.**

Per the operator rule in §20.1: every PR gets a design document here, and
**no implementation begins until the operator has reviewed and approved
it.** §20 is deliberately scope-level; the audits it requires routinely
change the design, so a PR must not be implemented from §20 alone.

## Status

| PR | Document | Status |
|---|---|---|
| **A** | [`pr_a_isolated_preflight_wiring.md`](pr_a_isolated_preflight_wiring.md) | **Approved 2026-07-31 — implementation in progress.** All 5 decisions resolved (§16). GPU validation not yet approved |
| **B** | `pr_b_gpu_aggregation_attribution.md` | Not started — conditional on PR A's dual-chain validation |
| **C** | `pr_c_measured_evidence_admission.md` | Not started |
| **D** | `pr_d_healthgate_formal_policy.md` | Not started — needs an operator policy decision first (§12A.4) |
| **E** | `pr_e_campaign_scoped_control.md` | Not started |

## Why PR A's audit mattered

PR A was scoped in §20.3 as "a call-site replacement, not a rewrite".
The audit found three material gaps between what production consumes and
what the isolated worker can express, one of them a hard blocker
(`vram_budget_gb=None` cannot be represented in `IsolatedProbeSpec`).

The PR stays local — no algorithm, policy or subprocess-architecture
change — but it needs a compatibility adapter, not a substitution. This
is the pattern the per-PR-document rule exists to catch: **the audit
belongs before the code, not inside it.**

## Convention

Each document carries the §20.11 review template filled in, the required
pre-implementation audit already performed with evidence citations, the
commit plan, the checkpoints, and the validation plan. This mirrors
`docs/design/v19_priorities/`, where the same workflow caught scope and
factual errors in review rather than in code.
