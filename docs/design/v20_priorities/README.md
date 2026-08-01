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
| **A** | [`pr_a_isolated_preflight_wiring.md`](pr_a_isolated_preflight_wiring.md) | **COMPLETE AND VALIDATED 2026-08-01 — ready to merge (PR #152, unmerged).** A5 PASS (contract regression found, repaired, revalidated 10/10); A6 PASS — parents 0 MiB, 125.9 s concurrent training, pair peak 15.52 GiB vs V19's 28.05 GiB. Verdict: `A6 PASS — PR A READY TO MERGE; PR B REQUIRED BEFORE V20 LAUNCH` |
| **B** | [`pr_b_gpu_aggregation_attribution.md`](pr_b_gpu_aggregation_attribution.md) | **REQUIRED — no longer conditional. DRAFT audited 2026-08-01, awaiting operator review.** A6 measured a candidate admitted at a 6.43 GB estimate holding 12.52 GiB, past the 12 GiB cap it was admitted under, and confirmed `pair_admission.py` has zero Python callers while both shell callers discard its verdict by default. Five commits (accounting → OOM context → attribution → headroom guard → docs). **Four open decisions block B-C1**, chiefly D-B1: no peer identity exists anywhere in Python, so the design proposes measuring "everything else" rather than building a cross-chain registry |
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

The same held for the validation plan — twice, in opposite directions.

The §21 audit argued the original criterion "the parent never appears
in `nvidia-smi`" was unachievable, because `hardware_context.discover()`
initializes CUDA before any pre-flight runs, and rewrote §10/§13 around
a measured **delta** instead. Running A5 refuted that: `discover()` does
set `torch.cuda.is_initialized()`, but it registers **no compute
process** — only a real allocation does. The original criterion was
achievable all along, and A5 met it. §22.2 records the retraction.

The lesson is the same one §1.3 states. A correct reading of the source
is not a prediction about the running system, and it must not be used
to relax a criterion before it has been measured. The audit was right
to find the gap and wrong to conclude what it did without testing it.

## Convention

Each document carries the §20.11 review template filled in, the required
pre-implementation audit already performed with evidence citations, the
commit plan, the checkpoints, and the validation plan. This mirrors
`docs/design/v19_priorities/`, where the same workflow caught scope and
factual errors in review rather than in code.
