# V20 Priorities — per-PR design documents

The authoritative plan is `docs/design/v20_priorities.md`. That document
records what V19 exposed, what V20 must fix, and the scope of each PR
(§20). **This folder is where each PR's actual audit findings, design
decisions and commit plan live.**

Per the operator rule in §20.1: every PR gets a design document here, and
**no implementation begins until the operator has reviewed and approved
it.** §20 is deliberately scope-level; the audits it requires routinely
change the design, so a PR must not be implemented from §20 alone.

## Binding principle — gradual genericization

Every document in this folder is bound by `v20_priorities.md` §1.4.
Each PR design **must** carry a "Genericization impact and in-passing
refactor" section answering the seven questions in §1.4.5, and each PR's
checklists must include the shared items in §1.4.6. Every PR now has a design document. PR C, D and E carry the
genericization requirements recorded in `v20_priorities.md` §20.5-20.7
into their own documents.

The standing review question:

> Does the code this change touches still treat TIDMAD, the current
> task, or the current machine as the framework itself? If so, can that
> be moved outside the configuration or plugin boundary within this
> PR's reasonable scope?

## Hardcoding audit — 2026-08-01

Classified per §1.4.4. Not every number is a defect; what matters is
whether it is labelled for what it is.

| Document | Assumption | Classification | Correction | Now / deferred |
|---|---|---|---|---|
| v20 §1.4 | — | policy added | four dimensions, three categories, config hierarchy, checklists | **now** |
| PR B | 12 GiB per-attempt cap | hardware-owned configuration | consumed from resolved policy; constant retained as a labelled compatibility default | **now** (design) |
| PR B | 28 GiB pair ceiling | hardware-owned configuration | same; `pair_admission.py:45` labelled a compatibility default | **now** (design) |
| PR B | 30,000 MiB host quota | hardware-owned configuration | must be declared; today `None` means *unknown*, not *unlimited* | **now** (design) |
| PR B | 29,000 MiB emergency line | **example fixture** — A6 validation only | never shipped in product code | **now** |
| PR B | phase names "training"/"inference" in the accounting primitive | unacceptable hardcoding | caller supplies a phase identifier | **now** (design) |
| PR B | `segmentation_size` in attribution wording | task-specific interpretation | generic layer returns typed authority; task layer owns the wording | **now** (design) |
| PR B / PR A | `_ROLE_DEFAULT_RSS_GB` keyed by task phase name | hardware policy + task coupling | out of PR B's touched scope | deferred **FU-B-6** |
| PR B | `MAX_CONC=2` | campaign policy | PR B changes no launcher | deferred **FU-B-7** |
| PR B | full `ResolvedRunConfig` | direction, not this PR | smallest typed subsection only | deferred **FU-B-8** |
| PR A | `HardwareSnapshot` single device, `device_index` default 0 | hardware-owned configuration | reconcile with PR B's `DeviceIdentity` rather than keep two shapes | deferred **FU-A-13** |
| PR A | estimator's model-family knowledge | task-specific, **correctly placed** | none — it is outside the generic worker layer | n/a |
| PR C | calibration records as universal facts | unacceptable hardcoding | index by task / dataset / phase / config / hardware / measurement type | requirement recorded |
| PR D | `unique_int8 > 25`, amplitude collapse | task-owned configuration | already in `health_checks.yaml`; PR D must not move it into the orchestrator | requirement recorded |
| PR E | `MAX_CONC=2`, `arch`/`loss` names in paths | campaign + task shape | chain identity and role from configuration | requirement recorded |

Deliberately **not** changed: `data_scope`, `health_gate_files`,
`segmentation_size` and model family names where they appear as
worked examples or as descriptions of what V19 actually ran. Those are
example fixtures and historical record, and rewriting them would
destroy evidence to satisfy a naming rule.

## Status

| PR | Document | Status |
|---|---|---|
| **A** | [`pr_a_isolated_preflight_wiring.md`](pr_a_isolated_preflight_wiring.md) | **MERGED 2026-08-01** — PR #152, merge commit `5c18946`. Validated before merge: A5 PASS (contract regression found, repaired, revalidated 10/10); A6 PASS — parents 0 MiB, 125.9 s concurrent training, pair peak 15.52 GiB vs V19's 28.05 GiB. The pre-merge verdict was `A6 PASS — PR A READY TO MERGE; PR B REQUIRED BEFORE V20 LAUNCH`, and both halves of it have since happened |
| **B** | [`pr_b_gpu_aggregation_attribution.md`](pr_b_gpu_aggregation_attribution.md) | **MERGED 2026-08-02** — PR #153, merge commit `4472f15`. All checkpoints landed: B-C1 accounting, B-C2a1/a2 execution seam, B-C2b bounded evidence, B-C3a/B-C3b attribution, B-C4 headroom guard, B-C5 doc sync; gates B-G1/B-G2/B-G3 run under operator approval; D-B1..D-B5 resolved, D-B4 shipped fail-closed by default. The attribution vocabulary is production code, not a proposal — `core/runtime_control/failure_attribution.py:49-52`, with reduction authority frozen to `candidate_gpu_capacity` alone |
| **C** | [`pr_c_measured_evidence_admission.md`](pr_c_measured_evidence_admission.md) | **COMPLETE — both halves merged.** **C1** MERGED 2026-08-03 (PR #161, `781e3e8a`) — calibration identity / reachability / promotion; C-C5b (production consumption of historical duration) CANCELLED by operator decision 2026-08-02, historical duration is observability-only. **C2** MERGED 2026-08-04 (PR #164, `40d17f69`) — authoritative GPU requirement acquisition and delivery. Gate 1 N/A; Gate 2 Lite-A (RTX 5090) PASS; Gate 2 Lite-B (H100 80GB HBM3) PASS; Gate-tested SHA `7302c467`. The measured claim, on both machines: the allocator under-reports by 627–1827 MiB, so the authority is driver-visible, candidate-owned, ancestry-attributed process-tree memory. Peaks differ per card **by design** — nothing travels between machines. **D-B5 is therefore satisfied**: PR B's admission gate now has a production input. |
| **D** | [`pr_d_formal_healthgate_and_valid_trial_policy.md`](pr_d_formal_healthgate_and_valid_trial_policy.md) | **DESIGN — awaiting operator review.** Audit complete against `dd8d66aa`. Four deviations proposed: D-D-1 (zero valid trials refuses AUTHORITY, not the round), D-D-2 (the declared mode is verified against the resolved config, not merely recorded), D-D-3 (gate ids that say `blocking` while resolving `continue`), D-D-4 (`would_invalidate_under_production_policy` becomes the counterfactual of record). Still needs the §12A.4 operator decision on the default mode for formal campaigns. |
| **E** | [`pr_e_campaign_scoped_control_state.md`](pr_e_campaign_scoped_control_state.md) | **DESIGN — awaiting operator review.** |

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
