# PR D — Formal HealthGate mode and the zero-valid-trial policy

**Status: IMPLEMENTATION IN PROGRESS — 9 of 10 checkpoints complete.**
D-C1a (`b751476b`), D-C1b (`8bdeb7d1`), D-C2a (`c8019e77`),
D-C2b (`84511954`, reinforced `8985d00f`), D-C3 (`7a52e450`, reinforced
`42a9f679` closing FU-D-6 + FU-D-8), D-C4 (`eb789271`, reinforced `7a128f18`
closing FU-D-9), D-C5 (`4767c72a`), D-C6 (`3e91adb6`), D-C7b (this commit). The formal-gate policy is FROZEN in §16 after two
read-only audits and the operator's negative-infinity bootstrap ruling
(2026-08-05).

**D-C9 was WITHDRAWN on 2026-08-05, so PR D is a 10-checkpoint PR.**
Historical records missing the new authority contract stay readable and
unchanged, with scientific authority simply not established — no
annotation, no sidecar, no reconstruction, no finer classification. The
249-artifact audit under D-C4 is the evidence for why (see §15.E).

Predecessor FU-D-10 merged to master as PR #172 (`51bab481`) and is
integrated here at `12506d80`. Next: the combined bounded Gate 1, then
D-C8 (final audit + documentation closure). Not merged; no Draft PR yet; Gate 1 and Layer 3 not run.

> **§16 supersedes any earlier statement in this document that conflicts
> with it**, most consequentially the "explicitly overridden formal round"
> framing, which was reasoning from the name `force_formal_round` rather
> than from the code.

```text
Audited code baseline      af5339ce   (after PR E and the role hotfix #171)
Previous baselines         334d388d   (post-PR-E re-audit)
                           dd8d66aa   (PR C2 merged, 40d17f69)
Predecessor hotfix         af5339ce   (D-C7a — DONE, PR #171, master CI green)
Policy dependencies        none — all resolved (§14, §15)
Implementation             pending final operator approval; 10 commits, D-C7a removed
```

**Re-audited against master after PR E (§15).** The re-audit confirmed
this design's central premise by execution rather than by reading, found
that PR E changed nothing PR D depends on, and found **one production
defect that PR D must not build on top of** — two paths already disagree
about whether the same record is HealthGate-valid. The operator's ruling
(2026-08-05) resolves it inside D-C1/D-C3 rather than as a separate
commit; see §15.

Two questions remain, and neither is a policy decision: both are answered by
**reading code** at the commit that needs them (§14).

Per the folder rule in `README.md`, no implementation begins until the
operator has approved this document. §20.6 is scope-level; the audit changed
the design in five places (D-D-1 through D-D-5), and the second review
corrected eight more — most consequentially the `gate_role` definition
(§4.6), which as first drafted would have made the consistency check pass
V19's own configuration.

Parent scope: `docs/design/v20_priorities.md` §20.6.
Governing genericization contract: `v20_priorities.md` §1.4 (§8 here).
Predecessors: PR B (`4472f15`), PR C1 (`781e3e8a`), PR C2 (`40d17f69`).

**Dependencies**: none outstanding. The §12A.4 default-mode decision is
closed — a new formal campaign declares both dimensions or is refused
(§4.1). PR D touches no GPU measurement, no admission path and no O-7
accounting. One commit (D-C6) is LLM-facing and requires Gate 1.

**What this PR is NOT.** It does not retune a threshold, does not remove
observe-only mode, does not force a trial to succeed, and does not move any
scientific threshold out of `configs/health_checks.yaml` into orchestration
code. §20.6 is explicit that the last of those would undo the one thing the
current design already gets right.

---

## 1. Why this PR exists

V19 ran four rounds. **All four collapsed** — `unique_int8` of 1–4 out of
256, one round emitting a constant signal. Every round recorded
`would_invalidate_under_production_policy: true`. Every round resolved to
`continue`. Zero trials were valid. **Formal ran anyway, and its result
entered the record as an ordinary scientific result.**

The parent document (§12A) already established what this was and was not:

* the repository default config *does* invalidate failed blocking checks;
* V19 *explicitly selected* the observe-only config;
* `resolved_action=continue` was therefore **correct for that config**;
* so this was a **campaign-policy choice, not an enforcement defect**;
* the gate path, the thresholds and novel-architecture false positives are
  each ruled out by the artifacts.

That is the important framing and it survives this audit. Nothing here is a
bug in the gate machinery. The defect is that **the system had no way to
say which policy a campaign was running under, and no rule connecting "no
valid trial" to "no authoritative result".** Both are absences, which is why
a green test suite and a correct gate implementation coexisted with a
scientifically empty campaign.

### The one-line statement of the gap

```text
the gate knew the round was collapsed          would_invalidate_under_production_policy: true
the config said to continue                    on_fail: {action: continue}
the formal round ran                           force_formal_round -> plan.is_trial = False
the result was indistinguishable from a good one
```

Every step is individually defensible. The composition is not.

---

## 2. Objective and non-goals

**Objective.** A formal scientific campaign must state which HealthGate mode
it runs under, and a formal result produced with **zero valid trials must
not be able to become authoritative** — not in incumbent selection, not in
scientific aggregation, not in the report.

**Non-goals**, restated from §20.6 and reinforced by the audit:

| Not this PR | Why |
|---|---|
| retuning `min_unique_int8_values: 25` or amplitude thresholds | no new evidence; §20.6 excludes it explicitly |
| removing observe-only mode | it is legitimate for baseline characterization, threshold studies, diagnostics and gate calibration |
| forcing a trial to succeed | a collapsed trial is *information*; suppressing it is worse than recording it |
| moving thresholds into the orchestrator | §1.4.2 — that is the task layer's property, and `health_checks.yaml` already has the right shape |
| changing gate ordering, severity resolution, or `GateAction` semantics | out of scope; PR D changes *authority*, not *mechanism* |

---

## 3. Audit findings that shape the design

All citations verified against `master` at `dd8d66aa`.

### 3.1 The mode is implied by a filename, never named

There is no campaign "mode". There are two config files:

```text
configs/health_checks.yaml                          on_fail: invalidate_round
configs/health_checks_baseline_observe_mode.yaml    on_fail: continue
```

Selection is by path. `execute_tools/health_checks/config.py:28` defaults to
`configs/health_checks.yaml`; the tuner exposes an override at
`nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:5691`
("*Optional HealthGate YAML override; omitted uses configs/health_checks.yaml*").

The effective config **is** provenanced: `config.py:353` materializes
`{workspace}/health_checks_effective.yaml` atomically, and the run-invariants
lock pins its sha256. So an auditor can prove *what policy ran*.

**What they cannot do is read the mode.** Recovering it means diffing the
materialized YAML against a known-blocking baseline and inferring intent.
That is a reconstruction, not a record — and it is the reason the V19 report
does not obviously say "this campaign could not invalidate anything".

### 3.2 The observe-only config's gate ids still say `blocking`

`configs/health_checks_baseline_observe_mode.yaml`:

```yaml
  - id: output_diversity_blocking      # <- says blocking
    ...
    on_pass: {action: continue}
    on_fail: {action: continue}        # <- is not
    reason: Observe only; production policy would invalidate a failed result.
```

The `reason` is honest. The **id is not**, and the id is what appears in
`health_gate_results`, in records, and in operator-facing output. Three gates
carry this contradiction (`output_diversity_blocking`, `output_std_blocking`,
`amplitude_collapse_blocking`).

§20.6's merge criterion "labels do not contradict effective behaviour" is
therefore not a hypothetical — it names a live defect, and it is the cheapest
real improvement in this PR.

### 3.3 The system already knows, and already says so

`scripts/run_comparison.py:489` consumes
`would_invalidate_under_production_policy` across persisted gate results.
The field exists on every gate result and was **true on all four V19 rounds**.

This is the single most important audit finding for the design: **the
counterfactual is already computed and persisted.** PR D does not need to
invent a signal. It needs to give that signal *authority consequences*.

### 3.4 Valid-trial counting exists and is deliberately unused

`nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:5270-5273`:

```python
valid_trial_records = [r for r in valid_records if r.get("is_trial", False)]
valid_trial_top_record = (
    max(valid_trial_records, key=lambda r: r["denoising_score"])
    if valid_trial_records else None
)
```

with the comment at `:5266-5269` stating this is the **bookkeeping** notion
(HealthGate-valid trial records only), deliberately *not* identical to
`_best_trial_winner`'s gate predicate, and — decisively —
**"Read-only: nothing consumes these fields in V19."**

So `best_valid_trial_exp_id` / `best_valid_trial_denoising_score`
(`:5332-5336`) are already persisted per iteration and consumed by nothing.
`valid_trial_records == []` **is** the zero-valid-trial condition, already
materialized, one `if` away from being enforceable.

### 3.5 The formal override is explicitly designed to survive a dead trial stage

`ml_hyperparameter_tune_agent.py:1455-1492`. `force_formal_round` sets
`plan.is_trial = False`, then dispatches inheritance. The no-winner path:

> Shared no-winner fallback for `full_clone` and `hybrid_params`: when
> `memory_history` carries no HealthGate-valid trial round, the planner's
> plan is preserved unchanged and a WARNING is logged (**resilient — a messy
> trial stage shouldn't kill the chain**).

That comment is the V19 defect stated as an intention. It is also **not
wrong**: a messy trial stage genuinely should not kill the chain. The error
is the unstated leap from *"the chain continues"* to *"the result it
produces is authoritative"*. PR D separates those two, and **preserves the
resilience** — see D-D-1.

### 3.6 The incumbent is already partly protected — and has a hole

`core/resume.py:200-215` documents `chain_best_valid_formal_*` as the
DECISION-STATE incumbent: the best **commit-time-HealthGate-valid** formal
score, with `validity_basis` and `artifact_verified` provenance;
`resume.py:306-310` states commit-time validity only, the repo-current
`configs/health_checks.yaml` is **never** consulted for decision state, and
candidates whose commit-time validity cannot be established are UNKNOWN and
excluded.

That is a good design and PR D should not disturb it. **The hole is
orthogonal to it.** A zero-valid-trial formal round can pass *its own* gates
— collapse in the trial stage does not guarantee collapse in formal — and it
is then commit-time valid, and it enters the incumbent. Gate validity of the
formal round is a different question from whether any valid trial ever
supported the plan that produced it.

### 3.7 A validator already assumes observe mode, in one artifact class

`core/campaign_artifacts.py:49-53`:

```python
if result.get("resolved_action") != "continue":
    errors.append(f"gate {gate_id}: observe action is not continue")
```

This is a **baseline** artifact validator that requires observe-only
behaviour. It is correct for what it validates and must not be broken by a
mode field. Recorded so the implementation does not "fix" it.

### 3.8 Audit items from §20.6 with nothing to report

`Best score: None` — no separate defect found; it is the honest rendering of
`best_denoising_score: None` at `:5318` when `top_record` is `None`. The
label is arguably unhelpful but it is not lying. **Deferred as FU-D-4**
(reporting clarity), not fixed here.

Planner feedback: `_build_gate_exhaustion` at `:5279-5290` already assembles
gate-exhaustion feedback with `active_mode`, budgets and
`consecutive_fail_rounds_at_exit`. D6's structured all-trials-invalid
evidence should extend that existing block rather than open a second
feedback channel.

---

## 4. Design

### 4.1 Two dimensions, declared explicitly — never one mode, never inferred

**Operator decision 2026-08-04 (D-D-5).** `diagnostic` is *not* a third
HealthGate execution behaviour. Enforcement and authority answer different
questions and are declared separately:

```text
healthgate_mode    blocking | observe_only      what happens to CONTROL FLOW when a gate fails
result_authority   scientific | diagnostic      whether the result may ever be a SCIENTIFIC result
```

| `healthgate_mode` | `result_authority` | meaning |
|---|---|---|
| `blocking` | `scientific` | the normal formal V20 campaign |
| `observe_only` | `diagnostic` | baseline characterization, threshold study, gate calibration |
| `blocking` | `diagnostic` | a strict diagnostic run — gates enforce, results still carry no scientific authority |
| `observe_only` | `scientific` | **invalid — refused before launch** |

The fourth row is the V19 configuration, and refusing it at launch is the
single change that would have prevented the incident. It is refused
*before* any LLM or GPU work.

**Both are mandatory for a new formal campaign.** Omission does not default
to `blocking`, and neither is ever inferred from a config filename.
Historical manifests stay readable — the absence of the fields on an old
manifest is `unknown`, never a back-filled guess (§4.5).

Declared values are Pydantic-validated before reaching execution, pinned in
`RunInvariants` beside the existing `health_gate_enabled` /
`health_config_sha256`, and **verified against the fully resolved,
materialized effective config** — see D-D-2.

### 4.2 The valid-trial invariant

```text
valid_trials == 0  =>  no authoritative candidate exists for the iteration
                   =>  no formal result may receive scientific authority
```

**Running the formal round and certifying its result are separate
decisions** (D-D-1). That separation survives §16 and is in fact
strengthened by it.

> **SUPERSEDED BY §16.** The rest of this paragraph read: *"Zero valid
> trials does not cause a formal execution: formal runs only through an
> explicit diagnostic or `force_formal_round` override."* Both clauses
> are false against the code. Zero valid trials leaves the skip gate
> inert, so formal **does** run; and `force_formal_round` defaults to
> `True` and is the final-round phase transition, not an override
> (§16.A). The corrected launch rule is §16.D: **no valid winner ⇒ skip
> formal.** Authority remains a separate question and is decided from
> the formal record itself.

When it does run it is fully persisted, labelled `diagnostic`, excluded
from incumbent selection, excluded from scientific aggregation and grand
means, never reported as a formal scientific result, and the planner
receives structured `all_trials_invalid` feedback carrying the gate
evidence and reasons.

The condition itself is already computed (§3.4).

### 4.3 Authority is DERIVED from facts, never assembled by a caller

**Corrected twice by the operator.** The draft first missed the axis D-D-5
introduced — a run declared `result_authority: diagnostic` is
non-authoritative even with valid trials and blocking gates. It then still
allowed a caller to pass `authoritative`, `primary_basis` and `reasons`
independently, which permits states that contradict themselves:

```text
authoritative = true
reasons       = (no_valid_trial,)      <- cannot both be true
```

A verdict whose fields can disagree is not a verdict. **The only
constructor takes facts**; every conclusion is derived:

```text
ScientificAuthority.from_context(
    healthgate_mode,             blocking | observe_only
    declared_result_authority,   scientific | diagnostic
    valid_trial_count,           int  (iteration-level support context)
    formal_validity,             this record's own gate validity
)
```

Derived, and **not settable by any caller**:

```text
authoritative
primary_basis
enters_incumbent_selection
enters_scientific_aggregation
```

**Support and refusal are separate vocabularies**, because they answer
different questions and a run can carry several refusals at once:

```text
support_basis      valid_trial_supported | none

blocking_reasons   declared_diagnostic          operator declared it diagnostic
                   non_blocking_mode            healthgate_mode == observe_only
                   no_valid_trial               zero HealthGate-valid trials
                   gate_invalidated             this formal record failed its own gates
                   legacy_authority_unknown     a record predating these fields
```

```text
authoritative  <=>  blocking_reasons is empty  AND  support_basis is not none
```

`legacy_authority_unknown` closes a gap the draft had: §4.5 and the
incumbent rule both require a legacy record to be non-authoritative, but the
old basis list had no way to *say* so — it would have had to be squeezed
into `no_valid_trial`, which asserts something the record does not tell us.

`primary_basis` is the highest-precedence blocking reason, in the order
listed above; `blocking_reasons` carries **all** that apply, so a diagnostic
run that also had no valid trials reports both rather than losing one.

Authority is granted **only** for:

```text
healthgate_mode  == blocking
result_authority == scientific
valid_trial_count >= 1
the formal record itself meets the existing validity requirements
```

The consequences are computed properties — PR C's O-7 boundary is the
precedent: six frozen consequences derived from one disposition, so a new
consumer cannot forget one.

#### 4.3.1 The verdict's scope: one formal RECORD, carrying iteration context

The two inputs live at different levels, and the draft was inconsistent
about which the verdict belongs to. Fixed:

> **Every formal record carries its own `ScientificAuthority`**, which
> *references* the iteration's valid-trial support context.

```text
valid_trial_count   iteration-level    shared by every record of that iteration
formal_validity     record-level       this record's own gate outcome
```

Without this, the incumbent (which reads records) and the report (which may
read iteration summaries) could consult authority computed at different
levels and disagree.

#### 4.3.2 What `would_invalidate_under_production_policy` is NOT

Since `observe_only + scientific` is refused at startup (§4.1), the
counterfactual no longer decides authority. It is **not a second authority
gate**. Its uses are:

* a diagnostic reason in the recorded evidence;
* counterfactual reporting — "this round would have been invalidated";
* the structured collapse feedback of D-C6.

Stated because D-D-4 elevates it, and an elevated signal with no stated
boundary is how a second authority path gets built by accident.

### 4.4 Two consumers, one predicate

* **Incumbent** (`core/resume.py`): add `enters_incumbent_selection` to the
  existing commit-time-validity predicate. Do not replace it — §3.6.
* **Aggregation / report**: exclude records where
  `enters_scientific_aggregation` is false, and **state the exclusion**
  rather than silently shrinking the sample.

---

### 4.5 V19's artifacts are immutable; the classification is a sidecar

**Operator decision 2026-08-04.** V19's manifests are read-only forensic
evidence and are **not rewritten**. Back-filling `healthgate_mode:
observe_only` onto them would manufacture a record that the field existed
at the time, which is exactly the kind of retrospective tidying that
destroys the evidential value of an incident archive.

Instead a separate **closure annotation** is written alongside, recording:

* the original config path and its sha256;
* the verified observe-only classification, with the evidence it rests on;
* the date and basis of the retrospective classification (2026-08);
* hashes of the unchanged source artifacts, so the annotation can be shown
  not to have touched them.

This is the same principle PR E applies to historical STOP evidence:
preserve, annotate, never delete or rewrite.

### 4.6 Mixed *roles* are legal; mixed *semantics within a role* are not

**Operator decision 2026-08-04**, correcting this document's earlier
framing. "Some gates invalidate, some continue" is not a contradiction — it
is the shipped and correct configuration. `configs/health_checks.yaml`
already runs three blocking gates alongside recording-only ones
(`pearson_dispersion_recording`, `spectral_peak_ratio_recording`,
`per_file_output_std_recording`), and that is exactly right.

The rule is therefore keyed on **gate role**, not on the config as a whole:

**`gate_role` is a SCIENTIFIC property of the check, and is identical in
every config.** It says what the gate *is for*, not what the current
campaign does with it:

```text
output_diversity      role: blocking        collapse detectors — a failure
output_std            role: blocking        means the round's science is void
amplitude_collapse    role: blocking

pearson_dispersion    role: observational   metrics recorded for study;
spectral_peak_ratio   role: observational   a failure is not a verdict
per_file_output_std   role: observational
```

Both shipped configs declare **the same roles**. Only `on_fail` differs:

```text
gate_role = blocking       under `blocking` mode, on_fail MUST invalidate
gate_role = observational  on_fail MAY be continue / record-only
```

**This is the correction that makes the check work at all.** An earlier
draft of this document had the observe-only config declare its three
collapse detectors as `role: observational` — on the reasoning that the role
should describe the effective behaviour. That is exactly backwards, and it
would have destroyed the check:

```text
declare healthgate_mode = blocking
load the observe-only YAML
its three collapse gates are declared observational
-> no `role: blocking` gate resolves `continue`
-> THE CHECK PASSES
```

...on V19's configuration, which is the one case it exists to catch. A role
that tracks behaviour makes every config self-consistent by construction —
the same failure as inferring the mode from behaviour (§4.6.1). The role
must be invariant for the check to have anything to compare against.

| `healthgate_mode` | permitted | refused |
|---|---|---|
| `blocking` | blocking gates that invalidate **plus** observational gates that continue | **any** gate declared blocking whose `on_fail` resolves to `continue` |
| `observe_only` | every gate continues / records only | **any** gate holding invalidation authority |

So a mixed config passes under `blocking`; a *single* blocking-declared gate
resolving `continue` refuses the launch. That single case is the V19
configuration, and it is what the check exists to catch.

**This changes the commit order — see §4.6.1.**

#### 4.6.1 `gate_role` must land BEFORE the consistency check

The check in §4.6 is only as good as its notion of "declared blocking".
Without a typed `gate_role` the check has two options, and both are bad:

* **trust the `_blocking` suffix in the id** — perpetuating exactly the
  misleading label §3.2 documents; or
* **infer "blocking" from any gate that invalidates** — which cannot detect
  the one case that matters, a gate that *should* invalidate and does not.

The second is worth stating plainly: an inference-based check would have
passed V19's config, because inferring the mode from the behaviour makes
every config self-consistent by construction.

`D-C7` is therefore **split**, and its first half moves ahead of `D-C1b`:

```text
D-C7a  typed gate_role metadata          -> required BY the consistency check
D-C1b  the consistency check             -> consumes it
D-C7b  five-field output, display label  -> presentation, stays late
```

The presentation layer has no such dependency and remains near the end,
where a labels-only change belongs.

### 4.7 The exclusion reaches the report deterministically, not via the LLM

**Operator decision 2026-08-04.** How many non-authoritative results were
excluded, and why, **must** appear in the final report. It must **not**
depend on a model choosing to mention it.

Preferred, and the default:

```text
aggregation code filters deterministically
  -> deterministically derives the exclusion count and reasons
  -> the report renders a fixed provenance section
```

for example:

```text
Scientific aggregation used 3 authoritative results.
2 diagnostic/non-authoritative results were excluded:
  - 1 no_valid_trial
  - 1 declared_diagnostic
```

Passing the exclusion into an LLM-facing input is the **fallback**, taken
only if a code audit proves the final report is produced wholly by the
interpretation agent with no deterministic layer able to append to it. That
fallback is an LLM-facing behaviour change and requires separate operator
approval.

The reason for the preference is not only reliability: exclusion text inside
a prompt can influence the scientific interpretation the model then writes,
which is a contamination of a different kind.

## 5. Design deviations from §20.6

### D-D-1 — running formal and certifying it are separate decisions `[x]` APPROVED (operator, 2026-08-04)

§20.6 D2 reads "Zero valid trials ⇒ no authoritative formal scientific
result", and D3 permits a diagnostic formal marked non-authoritative. Read
together with §3.5's resilience intent, the implementable rule is:

> ~~**The round runs only if explicitly overridden. Whether it runs or
> not, its authority is refused.**~~
>
> **SUPERSEDED BY §16.** The first sentence was wrong — there is no such
> override, and the round runs by default. The corrected pair:
> **no valid trial winner ⇒ the round is skipped**, and authority, when a
> round does run, is decided from the formal record itself (§16.D).

**Operator refinement, 2026-08-04, PARTLY SUPERSEDED BY §16**: permitting
a diagnostic formal is *not* the same as automatically running one — that
half stands. The half that does not: *"Zero valid trials never causes a
formal execution — that requires an explicit diagnostic or
`force_formal_round` override."* Measured, zero valid trials **does**
cause one, because the skip gate returns `False` when there is no winner
(§16.B). §16.C/D replace the mechanism: no winner ⇒ skip. The two
decisions are independent, and only
the second is what D-D-1 governs.

Cancelling the round instead would (a) contradict the deliberate resilience
at `:1487-1489`, (b) destroy the evidence that a collapsed trial stage still
produced *some* formal behaviour, which is diagnostic information, and (c)
risk the §20.6 stop condition "would deadlock an iteration with no path
forward".

**This is the difference between a Gate and a kill switch, and it is the
same distinction PR C settled**: stopping the work and certifying the
evidence are separate decisions.

### D-D-2 — the declaration is CHECKED against the resolved config, not merely recorded `[x]` APPROVED (operator, 2026-08-04)

§20.6 D1 asks the manifest to state the mode plainly. Recording alone is
insufficient: an operator could declare `blocking` and pass the observe-only
YAML, and the manifest would then carry a *false* label with full sha256
provenance — strictly worse than today, because it would look verified.

So the resolved effective config is inspected and the declaration is
**verified against it**: if any gate whose declared role is blocking resolves
`on_fail: continue`, the run fails at startup with the mismatch named.

Fail-closed at startup, in the run-invariants tradition
(`core/run_invariants.py`), where a mismatched resume already refuses.

### D-D-3 — gate ids are never rewritten; the operator-facing label stops lying `[x]` APPROVED (operator, 2026-08-04)

Not in §20.6's checkpoint list; forced by §3.2. Either the role moves out of
the id into a declared field, or the observe-only config's ids stop saying
`blocking`. **Resolved by the operator, 2026-08-04.** Historical gate ids are **never
rewritten** — they are join keys in `health_gate_results` and in every
archived artifact. Instead, every new manifest and operator-facing report
records five fields together:

```text
gate_id             the stable identifier, unchanged forever
configured_action   what the config says on_fail
effective_action    what actually happened
healthgate_mode     blocking | observe_only
result_authority    scientific | diagnostic
```

An operator-facing **label** must not read `blocking` when
`effective_action` is `continue`. The old id survives as a compatibility
identifier; the display name is what changes.

### D-D-4 — `would_invalidate_under_production_policy` becomes the counterfactual of record `[x]` APPROVED (operator, 2026-08-04)

Not in §20.6. §3.3 shows the signal already exists and is persisted. Rather
than compute a second notion of "would this have failed under production
policy", PR D **elevates the existing field** to the input of the
authority verdict in `observe_only` mode. One definition, already validated
by V19's own artifacts.

---

### D-D-5 — enforcement and authority are two dimensions, not one mode `[x]` APPROVED (operator, 2026-08-04)

This document originally proposed a single `CampaignHealthMode` with three
literals (`blocking` / `observe_only` / `diagnostic`). Open Question 2 asked
whether `diagnostic` differed behaviourally from `observe_only`; the audit
had found no distinction available today, which is precisely the symptom of
a conflated axis.

The operator resolved it by splitting the axis rather than inventing a third
gate behaviour:

```text
healthgate_mode    blocking | observe_only     control-flow consequence of a gate failure
result_authority   scientific | diagnostic     eligibility to be a scientific result
```

`blocking + diagnostic` — a strict diagnostic run — is expressible under the
split and was **not expressible** under the three-literal design, which is
the concrete evidence the split is right. `observe_only + scientific` is
refused before launch, and it is the V19 configuration.

**Consequence for the commit plan**: commit 1 declares and records *two*
fields, and commit 2's consistency check gains the invalid-combination
refusal in addition to the mode↔config check.

## 6. Checkpoint tracker

| ID | Checkpoint | State |
|---|---|---|
| **D-C1** | `healthgate_mode` + `result_authority` typed and validated (D-D-5); manifest fields; **mandatory declaration, mode↔config consistency, and invalid-combination refusal** (D-D-2) | **D-C1a `[x]`** typed, recorded, manifest-stamped · **D-C1b `[x]`** five startup refusals at the chain boundary + launcher declares blocking+scientific |
| **D-C2** | `ScientificAuthority` verdict: computed consequences, typed `reasons`, fixed precedence incl. `declared_diagnostic` (§4.3); wired to the existing `valid_trial_records` (§3.4) | **D-C2a `[x]`** pure typed verdict, no call sites (`c8019e77`) · **D-C2b `[x]`** wired to every formal record (`84511954`, reinforced `8985d00f`) |
| **D-C3** | **The formal-LAUNCH correction**: no valid trial winner ⇒ skip formal; effective reference resolved per §16.C (rewritten 2026-08-05 — the previous "explicitly overridden" framing was factually wrong) | `[x]` **COMPLETE** — no-winner ⇒ skip, `-inf` bootstrap + provenance, one winner per formal round, JSON-safe persistence. 10/10 mutations caught. See the implementation record under Commit 6 |
| **D-C4** | Incumbent exclusion — extend `resume.py`'s predicate, do not replace it (§3.6) | `[x]` **COMPLETE** — authority is an additional conjunct; fail-closed `resolve_record_authority`; legacy ladder; 10-row matrix; 8/8 mutations. Found and fixed a D-C2b defect: the verdict was silently dropped by `ExperimentRecord` |
| **D-C5** | Aggregation/report exclusion, stated **deterministically** — not via the LLM (§4.7) | `[x]` **COMPLETE** — new `execute_tools/scientific_aggregation.py`; verdict consumed not re-derived; provenance rendered from the typed object, never by the model. 6/6 mutations |
| **D-C6** | Structured all-trials-invalid feedback | `[x]` **COMPLETE** — DEVIATION: a new `TrialValidityFeedback` carrier, because gate-exhaustion's triggers require budget-gated records and never fire here. Full producer→planner path, 7/7 mutations. Gate 1 pending |
| **D-C7a** | Typed `gate_role` metadata — **prerequisite for D-C1b** (§4.6.1) | `[x]` **DONE — predecessor hotfix `af5339ce`, merged 2026-08-05.** Not a PR D commit |
| **D-C7b** | Five recorded fields per gate; honest display label; **ids never rewritten** (D-D-3) | `[x]` **COMPLETE** — no config touched, `health_config_sha256` unshifted, no id renamed; label derived from the configured action. 5/5 mutations (two after fixing a redundant branch and a real coverage gap) |
| ~~**D-C9**~~ | ~~V19 retrospective closure annotation~~ | **WITHDRAWN — operator decision 2026-08-05.** Historical records stay readable and unchanged with authority simply not established; no annotation, no sidecar, no reconstruction. PR D is a **10-checkpoint** PR |
| **D-C8** | Doc sync — **skill, node, agent, launcher, CLI and example `.md` in the same change** | `[ ]` not started |

Mapping to §20.6: D1→D-C1, D2→D-C2, D3→D-C3, D4→D-C4, D5→D-C5, D6→D-C6.
D-C7b and D-C8 are additions this audit forced (D-C7a is done — see above).
D-C9 was added by the operator's V19-immutability decision and **withdrawn
on 2026-08-05**: historical records stay readable and unchanged with
authority simply not established, so there is nothing to annotate. Note
the ordering constraint: **D-C7a precedes D-C1b**, because a consistency
check without typed roles would have passed V19's own config (§4.6.1).

---

## 7. Commit plan

Eleven commits. Each is independently revertible and states its own Behavior
Delta. The ordering rule is PR C's: **the typed boundary lands before
anything consumes it**, so no commit adds branching to a consumer that
cannot yet be told the truth.

Nothing below is `[x]`. A step becomes `[x]` only when it is implemented
**and** verified with recorded evidence — the test name and count that
proved it, written back into this document at the checkpoint.

**Renumbered 2026-08-05**, after the predecessor hotfix (`af5339ce`)
landed `gate_role`, both config declarations and the shared resolver on
master. The former commit 2 (`D-C7a`) is **DONE and is no longer a PR D
commit**; everything after it moves up one.

| # | Commit | Behavior Delta |
|---|---|---|
| — | ~~`D-C7a` typed `gate_role` metadata~~ | **DONE — predecessor hotfix `af5339ce`**, not part of PR D |
| 1 | `D-C1a` mode/authority declared and recorded | none |
| 2 | `D-C1b` mode↔config consistency check | **mismatched declaration fails at startup** |
| 3 | `D-C2a` `ScientificAuthority` verdict, no call sites | none |
| 4 | `D-C2b` verdict wired at the tuner exit | records carry authority; nothing consumes it |
| 5 | `D-C3` formal-launch correction: no valid winner ⇒ skip formal; `-inf` bootstrap reference | **zero-evidence iterations stop spending a formal round; a fresh chain's gates become armed** |
| 6 | `D-C4` incumbent exclusion | **non-authoritative results stop entering the incumbent** |
| 7 | `D-C5` aggregation/report exclusion, deterministic (§4.7) | **non-authoritative results leave scientific aggregation** |
| 8 | `D-C6` all-trials-invalid feedback | planner receives structured evidence |
| 9 | `D-C7b` five recorded fields; honest display label | none (labels only) |
| ~~10~~ | ~~`D-C9` V19 closure annotation~~ | **WITHDRAWN 2026-08-05** — no annotation, no sidecar, no reconstruction |

**Scope corrections forced by the hotfix.**

- **`D-C1a` returns to its original scope** — campaign mode/authority
  declaration and recording. It does **not** carry the live classifier
  fix; that is already on master.
- **`D-C1b`'s consistency check now has a real input.** It compares the
  declared campaign mode against the **declared** `gate_role`s in the
  effective config, which is what makes the check non-circular: an
  inference-based check would have passed V19's own configuration.
- **`D-C2b` and `D-C3` consume role-aware *formal validity*** produced by
  the shared `resolve_scientific_gate_ids`, **not** a raw `gate_role`
  input. Neither should re-derive membership.
- **`D-C7b` must not describe the gate entry model as "gaining a role"** —
  it has one. Its remaining scope is the other recorded fields and the
  display label.
- **`D-C5` must name its module.** The re-audit established there is *no*
  deterministic report layer today (§15.D), so this commit creates one; it
  cannot be written as "filter the existing report path".

`D-C8` (doc sync) is not a numbered commit here: per the repository rule it
is the **last step before merge**, written against the merged code.

### Every code-bearing checkpoint runs the blocking CI pyright locally

**Operator requirement 2026-08-04.** PR C proved that a fully green pytest
run is not evidence of green typing: 44 pyright errors sat latent behind
2,416 passing tests, because CI had never run on the branch and pyright was
believed unrunnable locally. PR D adds several schemas, a typed verdict and
multiple consumers — the same exposure, larger.

> **A label defect in our own CI, found 2026-08-04 while writing this.**
> The workflow step is named *"Type check — pyright (strict, blocking)"*
> (`.github/workflows/ci.yml:43`), but `pyrightconfig.json` sets
> `"typeCheckingMode": "basic"`. The check is blocking and real; it is **not
> strict**. This document, PR A and PR B all repeated "strict" from the step
> name rather than the configuration.
>
> This is D-D-3's defect in our own toolchain — an operator-facing label
> asserting behaviour the effective configuration does not implement — and
> it is recorded here rather than fixed in passing, because changing either
> the name or the mode is a separate decision with different consequences.
> Filed as **FU-D-5**. Below, "the blocking CI pyright" means exactly what
> `uv run pyright` does today.

The system Node is v10.19.0 and too old, but **pyright-python caches its
own Node v26.2.0**, which reproduces CI exactly:

```bash
PATH=~/.cache/pyright-python/nodeenv/bin:$PATH ./.venv/bin/pyright
```

* after **every** schema or boundary checkpoint — focused pyright over the
  touched modules;
* before **every** push — the full CI-equivalent:

```bash
PATH=~/.cache/pyright-python/nodeenv/bin:$PATH ./.venv/bin/pyright   # 0 errors
./.venv/bin/ruff check .
./.venv/bin/ruff format --check .
./.venv/bin/python -m pytest tests/unit/ -m "not real_run" -q
# plus the structural / reachability mutation proofs for that commit
```

A second lesson from the same PR: a locally-green suite is still not a green
CI. The registry-fingerprint test passed on a dev box with `~/.siderius`
present and raised `KeyError` on a runner without it. Where a commit's tests
touch machine state, run them **both ways** before pushing.

> **Template note.** The operator's checklist template names ordering
> concerns (`file_order`, the `shuffle` path, visited sample sequence).
> Those belong to the V19 PR2 data-ordering work and have no counterpart in
> PR D, which changes no data selection. The equivalent obligation here —
> *validate the observed behaviour, not the configuration value* — is
> carried by requiring each acceptance criterion to name the **resolved
> action, the recorded verdict and the consumer's observed decision**,
> never merely the declared mode.

---

### Commit 1 — `D-C1a`: both dimensions are declared and recorded

**1. Goal.** Make `healthgate_mode` and `result_authority` *stated facts*
rather than something reconstructed by diffing YAML (§3.1, D-D-5). First
because every later commit reads them, and because it is pure addition — a
recorded field with no consumer cannot change behaviour. **Enforcement of
mandatoriness and of the invalid combination is commit 2**, so this commit
stays revertible without re-opening the launch path.

**2. Scope.**
- `agent/schemas/hyperparam_tuning.py` — the `HealthGateMode` and
  `ResultAuthority` literals and their input fields, alongside the existing
  `health_gate_enabled` (`:1662`) and `health_checks_config` (`:1030`,
  `:2244`).
- `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py` —
  CLI argument beside the existing `--health_checks` override (`:5691`);
  echo onto the output.
- `sdsc_submission_scripts/run_one_iteration.py` — stamp on the manifest.
- Docs: the node `.md`, `docs/design/pluggable_health_checks.md`.

*Non-goals.* No gate behaviour changes. No config file changes. The mode is
recorded and read by nothing.

*Dependencies.* None.

**3. Implementation plan.**
- [ ] Define `HealthGateMode = Literal["blocking", "observe_only"]` and `ResultAuthority = Literal["scientific", "diagnostic"]` in the schema module that already owns the HealthGate input fields (D-D-5 — two axes, not one).
- [ ] Add both fields to the tuner input schema. **No default** — the operator resolved Open Question 1: omission must not fall back to `blocking`. The field is optional at the schema level only so historical replays still load; the *launcher* refuses omission (commit 2).
- [ ] Add `--healthgate_mode` and `--result_authority`; mirror the wording of the existing `--health_checks` help text.
- [ ] Thread it onto `HyperparamTuningOutput` beside `health_checks_config` / `health_config_sha256`.
- [ ] Stamp both fields in `run_one_iteration.py`'s manifest **on every branch** (`completed` / `no_records` / `failed`), following the precedent set for `health_feedback_policy` and `preflight_execution_mode` (`:484-490`) — a crashed iteration is exactly when the mode matters.
- [ ] Import the value from the resolver rather than writing a literal, for the reason `PREFLIGHT_EXECUTION_MODE` already states: *"so the manifest and the mechanism cannot drift apart."*

**4. Validation plan.**
- *Unit*: each literal of each axis accepted; unknown strings rejected by Pydantic (not a hand-rolled `if`); both reach the output schema; **no default value is applied when omitted**.
- *Integration / pseudo*: a dual-mode tuner run carries the mode end-to-end into `run_output_*.json`.
- *Negative*: `--healthgate_mode nonsense` and `--result_authority nonsense` fail at parse time with the accepted values named.
- *Backward-compatibility*: an existing manifest **without** the field still loads through `core/resume.py::_read_manifest` (`:234`) — resume must not require the new key.
- *Real Gate*: none.

**5. Acceptance criteria.**
- [ ] A completed iteration's `manifest.json` contains `healthgate_mode` ∈ {blocking, observe_only} and `result_authority` ∈ {scientific, diagnostic}, **and** the pre-existing `health_config_sha256` unchanged in value and position.
- [ ] A `no_records` and a `failed` manifest also contain it.
- [ ] A manifest produced before this commit still loads without error.
- [ ] `grep` shows the manifest value is not a string literal at the write site.

**6. Failure and edge cases.**
| case | behaviour |
|---|---|
| either field absent on an old manifest | **fall back safely** — `unknown`, never back-filled and never assumed `blocking` (§4.5) |
| unknown literal | **stop** at schema validation |
| mode present, config absent | **stop** — recorded in commit 2, not here |
| chain resume across the upgrade | **warn**, record `unknown`, do not fail |

**7. Verification commands and evidence.**
```bash
./.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent/ -q
./.venv/bin/python -m pytest tests/unit/core/test_resume_incumbent.py -q
```
- [ ] test count: __   - [ ] wall time: __   - [ ] focused pyright: __ errors
Any test that cannot be run is recorded as **not run**, with the reason. It
is never reported as passed.

**8. Commit boundary.**
- [x] Independently reviewable: adds a field, changes no decision.
- [x] No unrelated cleanup; no follow-up work folded in.
- [x] Before committing: show diff summary, staged file list, test output, and any deviation from this plan.

#### IMPLEMENTATION RECORD — D-C1a `[x]` COMPLETE

**Commit**: `<filled at commit>`, on
`feature/v20-pr-d-formal-healthgate`, branched from `e1748dcc`.

**Behavior Delta: none.** 113 insertions, **0 deletions** — the diff is
pure addition, which is the mechanical form of "a recorded field with no
consumer cannot change behaviour".

**Production files changed**

| File | What |
|---|---|
| `agent/schemas/hyperparam_tuning.py` | `HealthGateMode` / `ResultAuthority` literals; both fields on the input schema and echoed on the output schema, **no default on either** |
| `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py` | `--healthgate_mode` / `--result_authority` (`choices=`, `default=None`); threaded into the input dict, the `run_config` provenance dict and `agent_output_dict` |
| `sdsc_submission_scripts/run_one_iteration.py` | manifest stamp on **every** branch, read off `tune_output` rather than written as a literal |

**Actual call path**

```text
CLI --healthgate_mode / --result_authority
  -> tuner input dict            (args.*)
  -> HyperparamTuningInput       (Literal, no default)
  -> run_config provenance       (agent_input.*)
  -> agent_output_dict           (agent_input.*)
  -> HyperparamTuningOutput      (echoed)
  -> manifest.json               (getattr(tune_output, …, None), every branch)
```

**Manifest, observed on all three branches** by executing
`write_manifest` rather than reading it:

| branch | `healthgate_mode` | `result_authority` |
|---|---|---|
| `completed` | the declared value | the declared value |
| `no_records` | `null` | `null` |
| `failed` | `null` | `null` |

`null` on the two non-completed branches is the honest answer, not a gap
to be filled: those paths have no tuner output, so there is no declaration
to report. Downstream must read it as "authority not establishable from
the declaration", never as a silent `blocking`.

**Tests** — 15 new in
`tests/unit/agent/schemas/test_healthgate_mode_declaration.py`; the
targeted set (schema + `test_run_one_iteration.py` +
`test_resume_incumbent.py`) is **99 passed in 1.34 s**.

Covering: every mode×authority combination accepted at the schema level
including `observe_only + scientific` (refused at the launcher in D-C1b,
not here, so historical artifacts stay readable); `blocking + diagnostic`
expressible, which is what proves the axes are independent; neither axis
defaulting; declaring one not implying the other; five unknown-value
rejections **including each axis being offered the other's vocabulary**;
the output echo; a legacy output without either key still loading; and
neither axis having become a required output field.

**Static**: pyright **0 errors, 4 warnings** — identical to the branch
baseline. `ruff check` and `ruff format --check` clean.

**Deviations from the plan — two, both implementation corrections**

1. **`tune_output` is initialised to `None` before the manifest branch.**
   The plan says "stamp on every branch"; `tune_output` is only bound on
   the completed branch, so the stamp as written would have raised
   `UnboundLocalError` on `no_records` and `failed` — precisely the
   branches the plan says matter most. Found by inspection, confirmed by
   executing both paths. This narrows nothing: it is what "every branch"
   requires.
2. **Both `run_config` and `agent_output_dict` are stamped**, not just
   the typed output. A `count == 1` assertion caught that the
   output-shaped key block occurs **twice** — one is run-configuration
   provenance, the other the typed output — and both already carry the
   DS5 HealthGate stamps. Stamping one and not the other would create
   exactly the provenance/output drift this field exists to prevent.

**Not done, deliberately**: no enforcement of mandatoriness, no refusal of
`observe_only + scientific`, no consistency check against the effective
config, no consumer of either field. All of that is D-C1b.

**Next authorized checkpoint**: D-C1b — the startup enforcement boundary,
and the first commit in this PR that changes launch behaviour.

---

### ~~Commit 2~~ — `D-C7a`: typed `gate_role` metadata — **DONE, NOT A PR D COMMIT**

> **Landed as a predecessor hotfix (`af5339ce`, PR #171, 2026-08-05)** and
> removed from the PR D sequence. It was pulled out because the post-PR-E
> re-audit found the same missing declaration causing a *live* defect on
> master — the in-run and resume paths disagreed about the same record —
> and any resume before PR D merged was exposed.
>
> The hotfix delivered more than this section planned: not only the typed
> field and both config declarations, but the single shared
> `resolve_scientific_gate_ids` that both production paths now call, plus
> the sha-keyed compatibility map for historical role-less configs.
>
> The rationale below is retained because it is still the reason the field
> must be **declared** rather than inferred, and D-C1b depends on it.

**Original rationale (historical).**

**1. Goal.** Give the consistency check in commit 3 a reliable notion of
"declared blocking". Without it the check must either trust the misleading
`_blocking` suffix (§3.2) or infer the mode from behaviour — and an
inference-based check **would have passed V19's config**, because inferring
the mode from the behaviour makes every config self-consistent by
construction (§4.6.1).

It is *before* the check and separate from the presentation work (commit
10) because only the metadata is a prerequisite; the display label is not.

**2. Scope.** Presentation only. The typed `role` already landed in commit 2 — **this commit does not touch the gate entry model's schema again**.

*Non-goals.* **No gate id is renamed** — ids are join keys in every archived
artifact. No display change; that is commit 10. No enforcement; that is
commit 3.

*Dependencies.* None.

**3. Implementation plan.**
- [ ] Read the gate entry model and `HealthChecksConfig` load path before choosing the field's shape.
- [ ] Add `role: Literal["blocking", "observational"]`. **No behaviour-preserving default for new configs**: a role inferred by default puts the consistency check back on a guess. A historical config that omits it reads as `legacy_unknown` and is refused for a NEW formal launch while remaining loadable for replay.
- [ ] Declare it on every gate in BOTH shipped configs, **with identical roles in each** — the three collapse detectors are `blocking` in both; only `on_fail` differs.
- [ ] Verify whether adding the key changes `health_config_sha256` for the shipped configs; if it does, record the expected new values and confirm no invariant lock compares across the boundary.

**4. Validation plan.**
- *Unit*: a role-less config loads with behaviour identical to pre-commit; both shipped configs declare a role on every gate; an unknown role is rejected by Pydantic.
- *Integration*: the materialized `health_checks_effective.yaml` carries the roles.
- *Negative*: `role: nonsense` refused at load.
- *Backward-compatibility*: a historical effective config without roles still loads.
- *Real Gate*: none.

**5. Acceptance criteria.**
- [ ] `git diff` shows **zero** changes to any gate id string.
- [ ] In BOTH configs the three collapse detectors declare `role: blocking`; the observe-only config still resolves them `on_fail: continue`. **That disagreement between role and effective action is the signal**, and it is what commit 3 refuses and commit 10 labels.
- [ ] A config omitting `role` is `legacy_unknown`: loadable for replay, refused for a new formal launch.
- [ ] A role-less config produces byte-identical gate behaviour.
- [ ] Any `health_config_sha256` change is recorded here with both values.

**6. Failure and edge cases.**
| case | behaviour |
|---|---|
| config omits `role` | `legacy_unknown` — loadable for replay, **refused** for a new formal launch |
| unknown role literal | **stop** at load |
| id says blocking, role says blocking, effective action is `continue` | **legal in observe_only, refused under blocking** — this is the V19 signature |

**7. Verification commands and evidence.**
```bash
./.venv/bin/python -m pytest tests/unit/execute_tools/ -q -k health
./.venv/bin/python -m pytest tests/unit/core/ -q -k "health or invariant"
```
- [ ] test count: __   - [ ] wall time: __   - [ ] focused pyright: __ errors
- [ ] `health_config_sha256` before/after: __

**8. Commit boundary.**
- [ ] Metadata only — no enforcement, no display change.
- [ ] Before committing: show that no gate id appears in the diff.

---

### Commit 3 — `D-C1b`: the declaration is mandatory, consistent, and never an invalid pair

**1. Goal.** Close D-D-2 and the launch-refusal half of D-D-5. Three
refusals, all before any LLM or GPU work:

```text
1  a new formal launch omits either field                 -> refuse
2  declared healthgate_mode != resolved effective config  -> refuse
3  observe_only + scientific                              -> refuse
```

Refusal 3 is the V19 configuration. A declaration that is merely *recorded*
can be false while carrying sha256 provenance — strictly worse than today,
because it looks verified. Separate from commit 1 because this one **can
fail a run**, and that blast radius deserves its own revert.

**2. Scope.**
- `core/run_invariants.py` — the natural home: it already pins
  `health_gate_enabled` and `health_config_sha256` (`:108-109`, `:136-142`)
  and already fails closed on a mismatched resume.
- Startup path in the tuner where the effective config is materialized
  (`execute_tools/health_checks/config.py:353`).

*Non-goals.* Does not change what any gate does; does not rewrite a config
to match a declaration. It refuses, it does not repair.

*Dependencies.* Commits 1 **and 2** — the check is keyed on `gate_role`, and without it the check cannot detect the one case that matters (§4.6.1).

**3. Implementation plan.**
- [ ] Inspect `RunInvariants` and its lock/compare path end to end before choosing where the check lives; do not assume the constructor is the right seam.
- [ ] Apply the **role-keyed** rule (§4.6), not a whole-config one: under `blocking`, refuse if any gate with `role: blocking` resolves `on_fail: continue`; under `observe_only`, refuse if any gate holds invalidation authority. Mixed roles are legal and must pass.
- [ ] Compare declared against effective; on mismatch raise with **both** values and the offending gate ids named.
- [ ] Add both fields to the locked invariant set so a resume under a different declaration fails the way a changed scope already does.
- [ ] Refuse `observe_only + scientific` explicitly, naming it as the V19 configuration in the message.
- [ ] Refuse omission **in the V20 formal launcher path only** — historical replays and diagnostic tooling must stay runnable.
- [ ] Confirm the check runs **before** any GPU work.

**4. Validation plan.**
- *Unit*: a **mixed-role** config under `blocking` → passes; a `role: blocking` gate resolving `continue` → refusal naming it; declared `blocking` + all-`continue` config → refusal naming the gates; `observe_only` + blocking config → refusal; `observe_only + scientific` → refusal regardless of config; `blocking + diagnostic` → **accepted**; matching pairs → pass.
- *Integration*: startup refusal happens before the first round.
- *Negative*: unreadable/absent effective config → refusal, never a silent pass.
- *Backward-compatibility*: a workspace locked before this field exists resumes without refusal (see Stop Condition 4, §11).
- *Real Gate*: none.

**5. Acceptance criteria.**
- [ ] A run declaring `blocking` against `configs/health_checks_baseline_observe_mode.yaml` **exits non-zero before any training**, and the message names `output_diversity_blocking`, `output_std_blocking`, `amplitude_collapse_blocking`.
- [ ] The equivalent correct pairing runs unchanged, and the recorded `health_config_sha256` is byte-identical to the pre-commit value for the same config.
- [ ] A pre-existing lock file without the fields resumes without refusal.
- [ ] `observe_only + scientific` exits non-zero before any training, with a message naming it as the V19 configuration.
- [ ] `blocking + diagnostic` launches normally and its results are non-authoritative.
- [ ] Omitting either field in the V20 formal launcher exits non-zero; omitting them in a historical replay does not.

**6. Failure and edge cases.**
| case | behaviour |
|---|---|
| declared ≠ effective | **stop** at startup |
| effective config unreadable | **stop** |
| legacy lock without the field | **fall back safely** — no refusal |
| mixed **roles** (blocking + observational gates together) | **allowed** — the shipped production config is exactly this (§4.6) |
| a `role: blocking` gate resolving `continue` | **stop** — the V19 case |
| `observe_only + scientific` | **stop** before any LLM or GPU work |
| omission in a non-formal/diagnostic path | **allowed** — only the formal launcher demands both |

**7. Verification commands and evidence.**
```bash
./.venv/bin/python -m pytest tests/unit/core/test_run_invariants.py -q
./.venv/bin/python -m pytest tests/unit/core/ -q -k "health or invariant"
```
- [ ] test count: __   - [ ] wall time: __   - [ ] focused pyright: __ errors

**8. Commit boundary.**
- [x] Independently reviewable and independently revertible — reverting restores commit 1's record-only behaviour.
- [x] Before committing: show the refusal message verbatim.

#### IMPLEMENTATION RECORD — D-C1b `[x]` COMPLETE

**Commit**: `<filled at commit>`, on top of D-C1a `b751476b`.

**Behavior Delta**: a chain iteration whose declared policy is missing,
self-contradictory, or contradicted by its HealthGate config now **exits 2
before any work**. Legal launches are unaffected.

> ### The dependency this checkpoint's plan did not state
>
> **Nothing on the production chain path passed the declarations.** D-C1a
> added the tuner CLI arguments; the launcher chain was never wired:
>
> ```text
> v19_queue_runner.sh → run_chain.sh → _chain_common.sh → run_one_iteration.py → tuner
>                     declarations passed at any hop:  0 shell files
> ```
>
> So refusing omission would have made **every production chain launch
> fail** — tests green, production dead. Operator ruling (2026-08-05): the
> chain declares **`blocking + scientific`**, wired in this commit. That is
> a statement of what a V19/V20 formal chain already is — it runs
> `configs/health_checks.yaml`, whose three role:blocking gates invalidate
> a round, and its results feed the incumbent and the science.

**Refusal seam — `run_one_iteration.py`, not the schema.** Operator ruling.
Two reasons, both load-bearing:

- the permissive schema is what keeps historical artifacts readable. An
  artifact recorded under `observe_only + scientific` documents an
  incident; refusing it at the schema would make that incident unopenable.
  Verified safe: `core/resume.py` reads manifests directly and **never**
  constructs a `HyperparamTuningInput`, so tightening the launch path
  cannot break historical reads.
- `validate_runtime_config` runs for *every* tuner invocation including
  diagnostic tooling (`scripts/bg_admission_validation.py:571` builds a
  tuner input). Refusing there would block diagnosis, and an exemption flag
  would be a bypass surface that can be used by accident.

**Production files changed**

| File | What |
|---|---|
| `execute_tools/health_checks/launch_policy.py` (**new**, 175 lines) | `validate_formal_launch`, `FormalLaunchPolicyError`, `_enforcing_gate_ids` |
| `sdsc_submission_scripts/run_one_iteration.py` | `--healthgate_mode` / `--result_authority`; the refusal as the first thing `main()` does with parsed args |
| `sdsc_submission_scripts/_chain_common.sh` | `HEALTHGATE_MODE=blocking`, `RESULT_AUTHORITY=scientific`, CLI passthrough, argv assembly |
| `execute_tools/health_checks/candidate_eligibility.py` | `resolve_scientific_gate_ids` / `legacy_config_body_sha` widened to `str \| None`, matching the loader they wrap |

**The five refusals, and what each prevents**

| # | Refusal | Prevents |
|---|---|---|
| 1 | `healthgate_mode` omitted | a run claiming enforcement nobody configured |
| 2 | `result_authority` omitted | a run claiming scientific standing nobody granted |
| 3 | `observe_only + scientific` | gates that only record certifying a result |
| 4 | declaration contradicts the config's enforcement | **the 08:17 shape**: the artifact says enforced, the run was not |
| 5 | inverted deltas **while gates are enabled** | both gates firing for one score, decided by statement order |

Refusal 5 is scoped to `enable_chain_incumbent_formal_gates` per the
operator: with the gates off the deltas are not consumed, so an unused
historical pair must not block a launch.

**Roles are not re-derived.** Scientific membership comes from the shared
`resolve_scientific_gate_ids` merged in `af5339ce`. Only *enforcement* is
action-derived (`_enforcing_gate_ids`), which is the correct question for
"does this config actually invalidate anything". Keeping the two apart is
the point of the hotfix.

**Why the source config suffices** — verified, not assumed:
`materialize_effective_config` only applies `apply_monitored_files`
(`peek_file_indices`) and `validate_health_scope`; it never rewrites
`on_fail.action` or `gate_role`. Enforcement semantics are therefore
identical before and after materialization, so the check can run at the
launch boundary without weakening.

**Verbatim refusal messages**

```text
[run_one_iteration] FORMAL LAUNCH REFUSED: a formal launch must declare
--healthgate_mode and --result_authority. There is no default: defaulting
to blocking/scientific would let this run claim enforcement and scientific
standing that nobody configured. Declare both explicitly.

[run_one_iteration] FORMAL LAUNCH REFUSED: observe_only + scientific is a
contradiction: gates that only record cannot certify a result. …

[run_one_iteration] FORMAL LAUNCH REFUSED: healthgate_mode=blocking, but
these role:blocking gates cannot invalidate anything in
'configs/health_checks_baseline_observe_mode.yaml':
['amplitude_collapse_blocking', 'output_diversity_blocking',
'output_std_blocking']. The declaration says enforced and the
configuration says observe — the artifact would record a policy the run
did not have.
```

**Tests** — 15 new in `test_formal_launch_policy.py`, 3 new reachability
tests in `test_run_one_iteration.py` (68 total there). Targeted suites
(`sdsc_submission_scripts` + `health_checks` + `core` + `agent/schemas`):
**2979 passed, 2 skipped** in 157 s. Full `tests/unit`: **7323 passed**,
2 skipped, 4 xfailed.

The reachability tests build argv **explicitly** and do not go through
`_run_main`, which now synthesises the declarations the production shell
supplies — a test using that helper could not observe an omission.

**Existing tests updated, with reasons**

- `_run_main` synthesises the two declarations, for the same stated reason
  it already synthesises `--run_name`: a shell-side convention production
  always supplies, in tests that target the argparse/wiring layer.
- `test_health_checks_config_reaches_workflow` now declares
  `observe_only + diagnostic`, because it drives the **observe-only**
  config. The helper's `blocking` default was refused — **the check
  catching a real mismatch in an existing fixture**, not a test defect.

**Mutations — five, all caught**

| mutation | fails |
|---|---|
| omission silently defaults to blocking+scientific | 4 |
| `observe_only + scientific` accepted | 2 |
| scientific membership inferred from the action | 2 |
| the chain boundary bypasses validation | 2 |
| the chain shell stops declaring the policy | 1 |

**Static**: pyright **0 errors, 4 warnings** — back to baseline after
widening two signatures that were needlessly narrower than the loader they
wrap (`str` vs the loader's `str | None`, where `None` means the shipped
default). `ruff check`, `ruff format --check`, `bash -n` clean.

**Deviations from the plan**

1. **The commit includes launcher wiring.** Unavoidable: the refusal is
   unusable without it, and shipping the refusal alone would leave the
   branch green while production could not launch.
2. **Two signature widenings in the predecessor hotfix's module.** Caught
   by pyright, not by tests. `None` is the loader's own convention for the
   shipped default; the narrower annotation was an oversight in `af5339ce`.

**Next authorized checkpoint**: D-C2a — the `ScientificAuthority` typed
boundary with no call sites.

---

### Commit 4 — `D-C2a`: the `ScientificAuthority` verdict, with no call sites

#### IMPLEMENTATION RECORD — D-C2a `[x]` COMPLETE

**Commit**: `<filled at commit>`, on top of D-C1b `8bdeb7d1`.

**Behavior Delta: none.** A pure typed value with **no production call
sites** — verified by grep: only tests import it. D-C2b wires it.

**File**: `core/scientific_authority.py` (new, 176 lines).

**Signature — launch history cannot reach it**

```python
ScientificAuthority.from_context(
    *,
    healthgate_mode: str | None,            # blocking | observe_only | None
    declared_result_authority: str | None,  # scientific | diagnostic | None
    formal_validity: FormalValidity,        # valid | invalid | unknown
) -> ScientificAuthority
```

Absent by construction, per §16.D: the trial winner, `valid_trial_count`,
the skip and bypass decisions, the comparison reference and
`force_formal_round`. Those decide whether the round was worth running;
this decides whether its result may be believed. A first formal result
that bypassed the budget on the `-inf` bootstrap is **no less
authoritative for it**. A test asserts the signature contains no
trial-shaped parameter and that the `AuthorityBlocker` vocabulary cannot
express `no_valid_trial`.

**Conclusions are structural, not validated.** `authoritative`,
`primary_basis`, `blocking_reasons`, `enters_incumbent_selection` and
`enters_scientific_aggregation` are `@computed_field` properties — there
is no constructor argument for them. `extra="forbid"` refuses a caller
that tries anyway. That second half matters: without it Pydantic
**silently discards** `authoritative=True`, so the verdict stays correct
while the caller believes they set it — measured during implementation,
which is why the config carries `forbid`.

**Truth table — executed**

| mode | authority | validity | authoritative | primary_basis |
|---|---|---|---|---|
| blocking | scientific | valid | **True** | `blocking_scientific_formal_valid` |
| blocking | scientific | invalid | False | `gate_invalidated` |
| blocking | scientific | unknown | False | `formal_validity_unknown` |
| blocking | diagnostic | any | False | `declared_diagnostic` |
| observe_only | diagnostic | any | False | `declared_diagnostic` |
| observe_only | scientific | any | False | `non_blocking_mode` |
| undeclared (`None`) | undeclared | any | False | `legacy_authority_unknown` |

Asserted as a property as well as row-by-row: **exactly one** of the
twelve combinations is authoritative.

`observe_only + scientific` returns a verdict rather than raising. D-C1b
refuses it at launch, but artifacts recorded under it exist and document
an incident — a pure function that threw on historical data would make
that history unreadable.

`blocking_reasons` reports **all** applicable reasons in a fixed
precedence, not just the first, so an operator fixing one can see the
others without re-running.

**Tests** — 25 in `tests/unit/core/test_scientific_authority.py`;
`tests/unit/core/`: **2045 passed, 2 skipped** in 44 s.

**Mutations — three, all caught**

| mutation | fails |
|---|---|
| `extra="forbid"` dropped (caller-set silently ignored) | 5 |
| `no_valid_trial` added to the blocker vocabulary | 1 |
| `unknown` validity treated as passing | 2 |

**Static**: pyright 0 errors / 4 warnings (baseline), ruff + format clean.

**Deviations**: none.

**Next authorized checkpoint**: D-C2b — wire the verdict onto every formal
record at the tuner exit.

**1. Goal.** Introduce the typed verdict and its computed consequences as a
pure unit. It is separate from its wiring for the reason PR C learned the
hard way: a boundary that lands together with its consumers cannot be
proven to be *reached*, and a verdict computed but never consulted is
exactly the defect class this PR exists to end.

**2. Scope.** One new module under `core/` owning `ScientificAuthority`,
its `from_context` constructor, the `support_basis` / `blocking_reasons`
vocabularies (§4.3), and the derived `authoritative`, `primary_basis`,
`enters_incumbent_selection` and `enters_scientific_aggregation` **as
computed values, never settable fields** — the shape
`prephase_admission.PrephaseAdmissionOutcome` already uses for O-7.

*Non-goals.* Zero call sites. Nothing imports it yet.

*Dependencies.* None (may land in parallel with 1–2).

**3. Implementation plan.**
- [ ] Read `core/runtime_control/prephase_admission.py` first and mirror its structure: frozen model, literal disposition, consequences as properties.
- [ ] Define the two vocabularies of §4.3: `support_basis` (`valid_trial_supported` | none) and `blocking_reasons` (`declared_diagnostic`, `non_blocking_mode`, `no_valid_trial`, `gate_invalidated`, `legacy_authority_unknown`).
- [ ] Carry `blocking_reasons: tuple[...]` with **every** applicable refusal, plus `primary_basis` as the highest-precedence one — a run can be `observe_only` AND `declared_diagnostic` AND have zero valid trials at once.
- [ ] Make `from_context` the ONLY constructor; a caller must not be able to state a conclusion.
- [ ] Implement the fixed precedence of §4.3 and test it directly.
- [ ] Make both `enters_*` properties `False` whenever `authoritative` is `False` — no independent path to `True`.
- [ ] Write the module docstring in the house style: what defect it prevents, and why the consequences are derived rather than flagged.

**4. Validation plan.**
- *Unit*: every basis; `authoritative=False` ⇒ both consequences `False`; the consequences cannot be set directly; **`declared_diagnostic` is non-authoritative even with valid trials and blocking gates**; a multi-reason case reports all reasons and the correct `primary_basis`.
- *Negative*: unknown basis rejected.
- *Mutation*: making a consequence an independent field must fail a test.
- *Real Gate*: none.

**5. Acceptance criteria.**
- [ ] For every input combination, the tuple `(authoritative, primary_basis, enters_incumbent_selection, enters_scientific_aggregation)` matches a table written in the test, hardcoded — never read back from the model.
- [ ] A self-contradictory verdict is **unconstructible**: there is no public path to set `authoritative` alongside a non-empty `blocking_reasons`.
- [ ] `blocking + scientific + >=1 valid trial + formal result valid` is the **only** combination yielding `authoritative: true`.
- [ ] A case with three simultaneous reasons lists all three.
- [ ] No production module imports the new one (`grep` evidence recorded).

**6. Failure and edge cases.** Unknown basis → **stop** (schema). Ambiguous
combination → unrepresentable by construction.

**7. Verification commands and evidence.**
```bash
./.venv/bin/python -m pytest tests/unit/core/test_scientific_authority.py -q
```
- [ ] test count: __   - [ ] wall time: __   - [ ] focused pyright: __ errors

**8. Commit boundary.**
- [ ] Independently reviewable: a pure module plus tests.
- [ ] Zero call sites is itself an acceptance criterion, not an omission.

---

### Commit 5 — `D-C2b`: wire the verdict at the tuner exit

#### IMPLEMENTATION RECORD — D-C2b `[x]` COMPLETE

**Commit**: `<filled at commit>`, on top of D-C2a `c8019e77`.

**Behavior Delta — stated precisely**: *selection* delta **none**;
*formal-record schema/provenance* delta **present**. Incumbent selection,
aggregation and reporting are untouched and behave exactly as before; what
changes is that every formal record now carries a verdict they may later
consume.

**Production files changed**

| File | What |
|---|---|
| `execute_tools/health_checks/candidate_eligibility.py` | `formal_validity_of(record, config_path)` → `Literal["valid","invalid","unknown"]` |
| `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py` | the formal-only authority block on `final_record` |

**Call path**

```text
final_record (one construction site, :4852)
  → if not trial_config.is_trial:
        formal_validity_of(final_record, config_path=agent_input.health_checks_config)
          → classify_candidate_health(record, resolve_scientific_gate_ids(cfg))   ← shared, role-aware
        ScientificAuthority.from_context(mode, authority, validity)               ← D-C2a, derived
      → final_record["scientific_authority"] = verdict.model_dump()
```

**The two asymmetries, both deliberate**

*Every* formal record gets a verdict — valid, invalid, diagnostic and
validity-unknown alike. A field present only on successes would make its
absence ambiguous.

*No* trial record gets one. Writing `authoritative: False` on a trial
would conflate "formal authority does not apply here" with "this formal
result was judged untrustworthy", and those call for opposite operator
responses.

**Validity is this record's own.** `formal_validity_of` reads the formal
record's gate results through the shared role-aware resolver. It cannot
see the trial winner, a trial count, the score, the skip/bypass decision
or `force_formal_round` — none is in scope at the call.

**Nothing is assembled locally.** A test asserts the tuner contains no
`final_record["authoritative"]`, `["primary_basis"]` or
`["blocking_reasons"]`; the conclusions come only from D-C2a.

**Persistence keeps every reason.** A diagnostic run whose formal record
also failed its gates round-trips as
`primary_basis: declared_diagnostic` **and**
`blocking_reasons: [declared_diagnostic, gate_invalidated]` — the gate
failure stays a diagnostic fact rather than being collapsed into the
headline. The three facts survive too, so the verdict is recomputable.

**`legacy_authority_unknown` is unreachable for new records** — D-C1b
refuses an undeclared launch. It exists for historical reconstruction, not
as a fallback. Asserted across all four declared combinations.

**Tests** — 15 new in `test_formal_authority_wiring.py`. Full
`tests/unit`: **7363 passed**, 2 skipped, 4 xfailed.

**Mutations — three, all caught**

| mutation | fails |
|---|---|
| formal wiring call site removed | 1 |
| verdict attached to trial records too | 1 |
| formal validity hardcoded instead of sourced from the record | 1 |

**Static**: pyright **0 errors** — after narrowing `formal_validity_of`'s
return from `str` to the exact `Literal`. pyright caught the mismatch; the
tests did not, because the value was always right. A new test pins the
classifier enum's values against `FormalValidity`'s literal so the two
vocabularies cannot drift apart in separate modules.

**Deviations**

1. **A flaky test from E-C6 was fixed in passing.** `TestTheLiveProcessGuardExcludesOnlyItself::test_the_exclusion_is_fixed_string_not_a_regex`
   failed once in a full-suite run and passed 3/3 in isolation. Cause: the
   fixture waited a fixed `sleep 0.4` for its process to appear in `ps`,
   which is a race under load — the guard then sees nothing and a
   "should block" case fails. Replaced with a bounded poll on `ps` in both
   the queue-runner and Gate-runner fixtures. Not D-C2b's scope, but a
   known flake left in CI is worse than the small out-of-scope edit, and
   it was mine.

**Coverage gap closed after review (same checkpoint, follow-up commit).**
Re-checking D-C2b against the operator's stated matrix found two rows the
first commit did not assert:

- *"no formal produced → no fabricated verdict"*. Now asserted on both
  non-completed manifest branches: `no_records` and `failed` carry **no**
  `scientific_authority` key, while still recording the declaration as
  `null`. A verdict invented where no formal round ran would be worse
  than a missing one — it would look like evidence.
- *"the record writer cannot override the derived fields"*. D-C2a's
  `extra="forbid"` protects the model, but the record holds a plain dict
  and nothing can stop a later writer mutating it. What **can** be
  guaranteed is that tampering is **detectable**: the facts are persisted
  beside the conclusions, so the verdict is recomputable from its own
  record. Asserted both ways — a clean record recomputes identically, and
  a record with `authoritative` flipped no longer matches its own facts.
  Plus a structural check that the tuner never writes *into* the
  persisted block.

Six further tests (21 in the file). One of them initially read another
test class's `setup_class` attribute, which made it depend on collection
order — a guard that silently becomes a no-op against `None`. Rewritten to
read the source directly and verified in isolation.

**Next authorized checkpoint**: D-C3 — the formal-launch correction, and
the first checkpoint in this PR that changes launch behaviour.

**1. Goal.** Compute the verdict from data that already exists (§3.4) and
attach it to the record. Separate from commit 3 so that "the verdict is
reached in production" is a distinct, provable claim.

**2. Scope.** `ml_hyperparameter_tune_agent.py` around the existing exit
bookkeeping (`:5255-5336`), reusing `valid_trial_records` (`:5270-5273`);
the output schema; the manifest mirror in `run_one_iteration.py` beside the
existing `best_valid_trial_score`.

*Non-goals.* **No consumer changes.** Incumbent and reporting are untouched
— commits 6 and 7.

*Dependencies.* Commits 1, 3 **and 4** — the verdict module itself (D-C2a) is required, not only the declaration and the check.

**3. Implementation plan.**
- [ ] Re-read `:5255-5340` before editing; the region is dense and adjacent to `_build_gate_exhaustion`.
- [ ] Compute the verdict from `valid_trial_records` and the declared mode. **Do not introduce a second notion of trial validity** — FU-D-3 records that two already coexist; use the bookkeeping one and say so in a comment.
- [ ] Attach to the output schema and mirror onto the manifest on every branch.
- [ ] Add a **reachability test** that fails if the production path bypasses the verdict.

**4. Validation plan.**
- *Unit*: zero valid trials ⇒ `no_valid_trial`; ≥1 ⇒ `valid_trial_supported`; `observe_only` ⇒ `non_blocking_mode` regardless of trial count.
- *Integration / pseudo*: a dual-mode run emits the verdict in `run_output_*.json`.
- *Negative*: absent/empty records ⇒ non-authoritative, never a default-authoritative.
- *Backward-compatibility*: existing consumers ignore the new field; scores and `best_*` fields byte-identical to pre-commit for the same inputs.
- *Real Gate*: none.

**5. Acceptance criteria.**
- [ ] For a run with zero valid trials, the record carries `authoritative: false`, `primary_basis: "no_valid_trial"`, `blocking_reasons` containing it, and **the same `best_denoising_score` as before this commit** — the verdict annotates, it does not alter the score.
- [ ] Deleting the verdict call from the production path fails a named test.
- [ ] `observe_only` yields non-authoritative even when trials are valid.

**6. Failure and edge cases.**
| case | behaviour |
|---|---|
| no records at all | non-authoritative, `basis` states why |
| mode unknown (legacy) | **warn** + non-authoritative — never assume `blocking` |
| both trial-validity notions disagree | **OPEN** — FU-D-3; record both, use bookkeeping, do not silently pick |

**7. Verification commands and evidence.**
```bash
./.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent/ -q
./.venv/bin/python -m pytest tests/integration/ -q -m "not real_run"
```
- [ ] test count: __   - [ ] wall time: __   - [ ] focused pyright: __ errors

**8. Commit boundary.**
- [ ] Reviewable as "compute and record"; no consumer reads it yet.
- [ ] Before committing: show that no incumbent or report file is in the diff.

---

### Commit 6 — `D-C3`: the formal-LAUNCH decision, corrected

#### IMPLEMENTATION RECORD — D-C3 `[x]` COMPLETE

**Commit**: `<filled at commit>`, on top of D-C2b reinforcement `8985d00f`.

> **Items 3, 5 and 8 below are SUPERSEDED.** They predate §16 and say
> *"mostly tests; any production change here is a red flag to surface, not
> to absorb"* and *"`completed_rounds` unchanged from pre-commit for the
> same inputs"*. §16.G assigns D-C3 **the no-winner ⇒ skip correction and
> the effective-reference resolution + provenance**, which are production
> changes by definition, and the whole point is that `completed_rounds`
> DOES change for a zero-valid-trial iteration. §16's supersession clause
> governs; this record states what was actually built.

**Behavior Delta**: **present, and intended.** Two decisions change, both
only when `enable_chain_incumbent_formal_gates` is ON:

1. an iteration with **no HealthGate-valid trial winner** now skips its
   formal round instead of spending it. `completed_rounds` is lower by one
   for exactly those iterations.
2. a chain with **no restored valid formal incumbent** now resolves the
   reference to `-inf` instead of `None`, so the first valid trial is never
   skipped and always bypasses the formal time budget.

With the switch OFF, behaviour is byte-identical to pre-D-C3 — asserted
through the real tuner loop, not merely by helper unit tests.

**Production files changed**

| File | What |
|---|---|
| `nodes/.../ml_hyperparameter_tune_agent.py` | `_should_skip_formal` / `_should_bypass_formal_time_budget` take a RESOLVED winner; `_resolve_formal_comparison_thresholds` gains `gates_enabled` and returns a 4-tuple with provenance; new `_json_safe_reference`; one winner resolved per formal round; the no-winner log line |
| `agent/schemas/hyperparam_tuning.py` | `formal_comparison_reference_source` **declared** on `HyperparamTuningOutput` (see the gap below); four descriptions state the null-when-infinite rule |
| `sdsc_submission_scripts/run_one_iteration.py` | the manifest carries the source beside the reference |

**The real producer → consumer path**

```text
agent_input.current_run_best_formal_score
  → _consumed_reference (gated on enable_chain_incumbent_formal_gates)
  → _resolve_formal_comparison_thresholds(gates_enabled=…)
      → (reference, skip_t, bypass_t, source)
  → run_config dict                          [:3371-3374]  sanitised
  → formal_trial_winner = _best_trial_winner(sandbox.get_summary())  [:3549]
      → _should_skip_formal(...)             [:3553]  → break, no formal round
      → _should_bypass_formal_time_budget(...) [:4233] → time_check["feasible"]=True
  → agent_output_dict                        [:5441-5444] sanitised
      → HyperparamTuningOutput.model_validate
      → run_output_{run}.json
      → run_one_iteration.write_manifest     [:452-462]
      → manifest.json → core/resume.py → the next iteration
  → partial_dict (degraded path)             [:5533-5536] sanitised
```

**Helper and schema changes**

| Symbol | Before | After |
|---|---|---|
| `_should_skip_formal` | `(memory_history, *, threshold)` | `(winner, *, threshold, gates_enabled)` |
| `_should_bypass_formal_time_budget` | `(memory_history, *, threshold)` | `(winner, *, threshold)` |
| `_resolve_formal_comparison_thresholds` | → 3-tuple | → 4-tuple, **required** `gates_enabled` |
| `_json_safe_reference` | — | new; `±inf → None` |
| `HyperparamTuningOutput.formal_comparison_reference_source` | — | new `str \| None` |

**Migrated tests — 18, not 17.** Each keeps the defect class it protected:

| Test | Defect preserved | Change |
|---|---|---|
| `test_explicit_zero_reference_remains_legal` | explicit 0.0 ≠ `None` | + asserts source is `restored_valid_formal_incumbent` |
| `test_none_reference_resolves_to_all_none` → `test_no_incumbent_bootstraps_to_negative_infinity_when_gates_are_on` | a missing incumbent never becomes a finite number, above all not 0.0 | **semantic rewrite**; the old rule is quoted in the docstring |
| `test_skip_gate_cannot_fire_without_incumbent` → `test_the_skip_gate_still_cannot_fire_on_a_valid_first_trial` | a fresh chain must not skip its first real candidate | **semantic rewrite**; same outcome, new mechanism (`-inf`, not `None`) |
| `test_bypass_gate_cannot_fire_without_incumbent` → `test_the_bypass_gate_now_fires_where_it_previously_could_not` | the v15 budget-block failure | **semantic rewrite, INVERTED outcome** — see deviation D-3 |
| `test_numeric_reference_resolves_sums`, `test_gates_consume_resolver_output_verbatim`, 3 × skip-gate, 3 × bypass-gate, 2 × disable-via-infinity | arithmetic, single-source, boundaries, escape hatches | 4-tuple + winner-first |
| `test_phantom_family_reference_is_just_a_number` | **no special-casing of 5.5763** | kept, strengthened — §16.C withdrew the seeded-baseline recommendation *because* of this phantom |
| `test_skip_formal_uses_valid_candidate_and_zero_reference` | an invalid trial can never open a gate | outcome flips (skip now fires); a second assertion at `threshold=-100.0` proves the reason is the absent winner, not the 9.0 |
| `test_bypass_uses_valid_candidate_and_half_point_threshold` | same, bypass side | outcome **unchanged**; + an `-inf` threshold case |
| `tests/integration/workflows/test_chain_incumbent_pseudo.py` | flag-OFF resolves to all-`None`, not fixed-0.0 | **the 18th consumer**, outside the stated 17 — see deviation D-2 |

New tests are consolidated in
`tests/unit/agent/tune_ml_hyperparam_agent/test_formal_launch_decision.py`
(29 tests): the 12-row matrix, the single-resolution property, the
persistence rules and three real-loop reachability tests.

**The 12-scenario matrix.** Every row asserts winner identity, skip,
bypass, ordinary-budget applicability, reference, source, both thresholds
and the JSON-safe persisted form (production posture: incumbent 10.0,
skip Δ 0.0, bypass Δ 0.5 → 10.0 / 10.5).

| # | scenario | winner | skip | bypass | ordinary | ref | source |
|---|---|---|---|---|---|---|---|
| 1 | no trial records | — | **T** | F | F | 10.0 | restored |
| 2 | all trials invalid | — | **T** | F | F | 10.0 | restored |
| 3 | invalid trial @ 99.0 | — | **T** | F | F | 10.0 | restored |
| 4 | valid winner, **no incumbent** | first | F | **T** | F | `-inf` | **bootstrap** |
| 5 | valid 9.0 (below skip) | weak | **T** | F | F | 10.0 | restored |
| 6 | valid 10.0 (**== skip**) | at_skip | F | F | **T** | 10.0 | restored |
| 7 | valid 10.2 (between) | middle | F | F | **T** | 10.0 | restored |
| 8 | valid 10.5 (**== bypass**) | at_bypass | F | **T** | F | 10.0 | restored |
| 9 | valid 11.0 (above bypass) | strong | F | **T** | F | 10.0 | restored |
| 10 | **gates disabled**, no valid winner | — | F | F | **T** | `None` | gates_disabled |
| 10b | gates disabled, valid winner | ignored | F | F | **T** | `None` | gates_disabled |
| 11 | restored valid incumbent | normal | F | F | **T** | 10.0 | restored |
| 12 | one winner for skip + bypass + logging + plan inheritance | — | — | — | — | — | — |

Row 12 is `TestTheWinnerIsResolvedOnce`: the inheritance path resolves the
winner independently inside `_apply_mode_override_chain`, so parity is
**proved** rather than assumed — a formal round forces `plan.is_trial =
False`, so nothing it appends can satisfy `_best_trial_winner`'s filter and
the round-boundary snapshot stays valid for the whole round.

Rows 1, 3 and 10 additionally run through the **real tuner loop** (resume
into a final formal round, only skill execution mocked).

**Mutation results — 11 run, 11 caught.** Baseline restored byte-identical
after each (sha verified), `__pycache__` cleared per run, anchors asserted
to match exactly once, and the clean baseline re-run at the end.

| # | mutation | caught by | n |
|---|---|---|---|
| M1 | no winner continues to formal | matrix 1/2/3, real-loop skip test, valid-candidate | 5 |
| M2 | missing incumbent stays `None` | matrix 4, bootstrap resolver + both gate tests | 4 |
| M3 | an invalid trial becomes eligible | matrix 2/3/10, inheritance, real loop, selection | 11 |
| M4 | skip `<` → `<=` | matrix 6, verbatim-consumption, valid-candidate | 3 |
| M5 | bypass `>=` → `>` | matrix 8, verbatim-consumption, margin, valid-candidate | 4 |
| M6 | gates-disabled behaviour altered | matrix 10, real-loop gates-off, valid-candidate | 3 |
| M7 | bypass re-resolves its own winner | `test_the_production_site_resolves_the_winner_exactly_once` | 1 |
| M8 | raw `Infinity` reaches an artifact | matrix 4, both `_json_safe_reference` cases, operator-disable | 4 |
| M9 | schema drops the provenance field | `test_the_provenance_survives_the_typed_output_and_the_manifest` | 1 |
| M10 | manifest drops the provenance field | `test_the_manifest_carries_the_source_beside_the_reference` | 1 |
| M11 | `in (-inf, +inf)` membership instead of `math.isfinite` | NaN sanitisation + the parametrised `nan` row | 2 |

*M7 is caught only by a structural assertion.* That is a real limitation
and is recorded, not papered over: while the trial history cannot change
mid-round the two resolutions agree by construction, so no behavioural test
can distinguish them. The companion test
`test_a_formal_round_cannot_add_a_trial_record_beneath_the_snapshot` proves
*why* they agree, which is the property actually worth guarding.

**Persistence audit.** Producers: three dict sites in the tuner
(`:3371-3374` run_config, `:5441-5444` agent_output_dict, `:5533-5536`
degraded partial_dict) — all four values sanitised at all three.
Consumers: `HyperparamTuningOutput` (built from the sanitised dict, so the
typed output cannot carry an infinity), `run_one_iteration.write_manifest`
(reads the typed output), `core/resume.py`. Internal arithmetic uses `-inf`
freely; nothing serialised does. `json.dumps(..., allow_nan=False)` is
asserted over every matrix row and over the operator-disable case.

**Validation**

| Check | Result |
|---|---|
| `test_formal_launch_decision.py` | 29 passed, 5.8 s |
| migrated + integration consumers | 66 passed, 6.8 s |
| `tests/unit/agent/tune_ml_hyperparam_agent/` | 881 passed, 189 s |
| schema + manifest + healthgate suites | 984 passed, 113 s |
| full `tests/unit` | **7407 passed**, 2 skipped, 4 xfailed, 428 s — see the note below |
| pyright (CI-equivalent, cached Node) | **0 errors**, 4 warnings — all pre-existing, none in a touched file |
| `ruff check` | All checks passed |
| `ruff format --check` | clean (3 files reformatted, all D-C3 lines) |
| `bash -n` | n/a — no shell script touched |

> **The full-suite run needs one note, because the raw number is
> misleading.** The first run reported `1 failed, 7406 passed`:
> `tests/unit/scripts/test_pr3_l2p_preflight.py::test_preflight_all_invariants`.
> It is **not** a D-C3 defect and not a test defect. It belongs to the
> unrelated PR3-L2-calibration protocol and asserts
> `no_production_file_modified` by running `git diff --name-only` — so it
> fails for **any** uncommitted production change, naming exactly this
> checkpoint's three files. Diagnosed by reading
> `scripts/pr3_l2_calibration/preflight.py:286-299`, then **proved** by
> staging the changes (which empties the worktree-vs-index diff) and
> re-running: `1 passed`. The suite is green for the committed tree, which
> is why the row above reads 7407.
>
> Consequence worth knowing: "full `tests/unit` green" is only assertable
> with a clean working tree, i.e. at or after commit — never mid-edit.

**Deviations from the frozen plan, and why each was necessary**

- **D-1 — D-C3 is a production change.** Items 3/5/8 of this section
  predate §16 and forbid exactly what §16.G assigns. Resolved in favour of
  §16, which states it supersedes conflicting text. No operator question:
  the conflict is settled by the document itself.
- **D-2 — an 18th consumer.** `test_chain_incumbent_pseudo.py:444` unpacked
  the 3-tuple and passed record lists positionally; it was outside the
  stated 17 and would have failed CI. Its defect class (flag-OFF resolves
  to all-`None`, not fixed-0.0) is preserved and strengthened with
  `source == "gates_disabled"`.
- **D-3 — a third semantics-changed test.**
  `test_bypass_gate_cannot_fire_without_incumbent` encodes the same
  superseded "no incumbent ⇒ inert" rule; under the bootstrap its assertion
  **inverts**. Rewritten with the change stated, not re-pointed.
- **D-4 — `gates_enabled` is a REQUIRED keyword**, not a defaulted one. A
  default of `False` would silently hand a forgetful caller the pre-D-C3
  behaviour — precisely the defect class this checkpoint fixes.
- **D-5 — `flush=True` on the new log line**, matching every other gate
  print. Chain stdout is piped to a log; an unflushed line interleaves.
- **D-6 — the provenance field was undeclared (a real gap, found by the
  step-7 audit and fixed here).** The tuner emitted
  `formal_comparison_reference_source` into its dicts, but
  `HyperparamTuningOutput` never declared it, so Pydantic's default
  `extra="ignore"` **silently dropped it** before `run_output_*.json` and
  the manifest — the two artifacts an operator reads. Nothing failed,
  because a dropped field is indistinguishable from an unset one. Without
  it, §16.C's persisted form is unimplemented and
  `formal_reference_score: null` stays ambiguous across three genuinely
  different runs. Closed by declaring the field, forwarding it in
  `write_manifest`, and M9/M10.
- **D-8 — NaN leaked past my own first implementation.** The audit's own
  requirement names `Infinity`, `-Infinity` **and `NaN`**; the first
  `_json_safe_reference` tested `value in (float("-inf"), float("inf"))`,
  which compares by equality — and NaN is not equal to itself. Verified by
  execution: `json.dumps({"t": _json_safe_reference(nan)})` produced
  `{"t": NaN}`. Reachable, because the deltas are operator CLI floats and
  `reference + nan` is `nan`. Replaced with a single `math.isfinite` check
  (M11). This is exactly the class of defect the step-7 audit exists to
  catch, and it was in the code under audit rather than in legacy.
- **D-7 — the reachability harness had to avoid a DS5 trap.** Stamping the
  seeded trial `health_gate_enabled: False` flips
  `classify_candidate_health` to **VALID** regardless of its gate results
  (`candidate_eligibility.py`, the self-describing disabled-mode waiver) —
  a combination that cannot occur in production and that silently defeated
  the harness. The tests run `health_gate_enabled=True` with an unstamped
  seed (DS6b reads that as "legacy = gates active"), and the reason is
  documented in the helper so it is not re-introduced.

**Follow-ups**

- **FU-D-6** `[x]` **CLOSED** by the reinforcement commit below.
- **FU-D-8** `[x]` **CLOSED** by the reinforcement commit below.
- **FU-D-7** *(new, **DEFERRED — operator decision 2026-08-05**)* —
  historical artifacts carry `formal_comparison_reference_source: null`,
  which does not distinguish "predates the field" from the three live
  cases. **Historical artifacts are NOT to be rewritten to populate it.**
  It is handled at the legacy-reconstruction / V19-sidecar checkpoint:
  emit a derived source where reconstruction is reliable, keep
  unknown/null where it is not, and never modify the V19 originals. Does
  not block D-C4.

---

#### REINFORCEMENT — D-C3 follow-up closure, NOT a new checkpoint

**Commit**: `<filled at commit>`, on top of D-C3 `7a52e450`. The
checkpoint count stays **5 / 10**; D-C4 is what makes it 6. (Total
revised from 11 to 10 when D-C9 was withdrawn, 2026-08-05.)

Operator-approved after D-C3 was accepted: close the two follow-ups that
are themselves launch-gate correctness, before starting D-C4.

**FU-D-6 — one winner snapshot, structurally**

`_apply_mode_override_chain` no longer calls `_best_trial_winner`; it
takes a required keyword-only `trial_winner`, and the tuner passes the
same snapshot the skip gate, the bypass gate and the log line used. The
two agreed before by construction — a formal round forces
`plan.is_trial = False`, so nothing it appends can satisfy the winner
filter — but §16.F requires one *snapshot*, not two computations that
happen to match, and the old seam would diverge the moment anyone added a
state update between the gates and inheritance.

`memory_history` stays, and is not redundant: the full-clone OOM-recovery
branch reads the latest record and the maximum `round_index` across the
whole history, which a winner alone cannot answer.

`trial_winner` is **required**, not defaulted — a `None` default would
make a forgetful caller silently mean "inherit nothing", a behaviour
change with no error. Cost: 27 test call sites migrated. In
`test_force_formal_round.py` a local `_override(...)` helper resolves the
winner from the supplied history through the real `_best_trial_winner`,
so the eligibility rules under test (collapsed excluded, formal excluded,
highest score wins) stay live rather than being bypassed by a hand-built
dict.

*New test that can actually see the guarantee*:
`test_inheritance_obeys_the_supplied_winner_over_the_history` hands
inheritance a history whose own best is `real_winner` while supplying
`weaker` (different `lr`) as the snapshot. Re-derivation inherits
`real_winner`; using the snapshot inherits `weaker`. The configuration
cannot arise in production — that is the point: it isolates *which*
source is consulted, which no production-shaped fixture can do.

**FU-D-8 — non-finite configured deltas are refused at launch**

Sixth refusal in `validate_formal_launch`. With the gates enabled, both
`skip_formal_min_delta` and `bypass_formal_time_budget_min_delta` must be
finite; `NaN`, `+inf` and `-inf` are refused, naming every offending
field at once.

Checked **before** the ordering rule, and that order is load-bearing:
`NaN > NaN` is `False`, so an unusable pair passes the ordering check
unnoticed. At runtime a non-finite delta makes every gate comparison
`False`, silently disabling both gates while the artifact still records
an enforced run — the same fail-open shape §16.C eliminated for the
missing bootstrap reference. Both fields are plain `float` on the schema
with no finiteness constraint, so this was reachable from the CLI.

**Scope, stated because conflating the two would break the bootstrap**:
what is refused is the *operator-configured delta*. The internally
resolved `-inf` comparison reference (§16.C) is a deliberate resolver
value and stays legal. `TestTheBootstrapIsNotRefused` pins the separation
by asserting the validator's signature never receives a reference, and
that the resolver still bootstraps to `-inf`.

Gates disabled → unchanged, matching the established D-C1b convention
that unused deltas must not block a launch (audited: that is exactly what
`test_inverted_deltas_are_ignored_when_the_gates_are_disabled` already
encodes).

**Validation**

| Check | Result |
|---|---|
| launch-policy + tuner + reachability (focused) | 112 passed, 6.4 s |
| `tests/unit/agent/tune_ml_hyperparam_agent/` + health_checks | 1159 passed, 189 s |
| full `tests/unit` | **7428 passed**, 2 skipped, 4 xfailed, 432 s — run with the tree staged, so the PR3-L2 preflight guard sees a clean diff (see the D-C3 note above) |
| pyright | **0 errors**, 4 warnings (pre-existing) |
| ruff / ruff format | clean, 580 files |

**Mutations — 5 run, 5 caught**

| # | mutation | caught by | n |
|---|---|---|---|
| R1 | inheritance re-derives its own winner | `test_inheritance_obeys_the_supplied_winner_over_the_history` | 1 |
| R2 | `trial_winner` gets a `None` default | `test_the_helper_cannot_silently_fall_back_to_the_history` | 1 |
| R3 | non-finite refusal removed | the 6 field×value cases + 2 | 8 |
| R4 | finiteness checked AFTER ordering | same | 8 |
| R5 | gates-disabled early return removed | inverted-delta compat + 3 scoping cases | 4 |

**Implementation detail found during the work.** `argparse` reads a bare
`-inf` as a flag (leading dash) and errors before the validator — fail-closed,
so safe, but not the path under test. The reachability tests use the
`--flag=value` form to reach the refusal, and say why.

**Next checkpoint**: D-C4 — incumbent exclusion, extending
`core/resume.py`'s commit-time validity predicate rather than replacing
it. Goal: only an authoritative formal result may update the chain
incumbent; invalid, diagnostic and unknown formal records stay persisted
but can never become the comparison basis for a later gate.

---

> **Rewritten 2026-08-05** after the two gate audits. The previous version
> of this section was **factually wrong** and is preserved only in Git: it
> claimed *"Zero valid trials **never causes** a formal execution — that
> requires an explicit diagnostic or `force_formal_round` override."*
> Both halves are false, and §16 has the evidence.

**1. Goal.** Correct the formal-launch decision so that the **absence of
valid trial evidence stops the spend**, instead of being indistinguishable
from sufficient evidence.

The measured defect (§16.B):

```text
winner = _best_trial_winner(memory_history)   # HealthGate-valid, this iteration
_should_skip_formal -> `winner is not None and winner.score < threshold`

winner is None  ->  returns False  ->  formal RUNS
```

`force_formal_round` does not rescue this and is not an override: it
defaults to `True` and means *the last round of every iteration runs in
formal mode regardless of what the planner picked* — the
cross-architecture comparability contract
(`hyperparam_tuning.py:1188-1206`). So formal on the final round is the
**default path**, and the skip gate is the **only** thing that can prevent
it. An inert skip gate therefore does not merely fail to stop a rare
override; it lets every zero-evidence iteration spend a full formal round.

**2. Scope.** The launch decision only:

- `winner is None` → **skip formal.** No valid trial is no evidence, and
  no evidence does not justify the cost.
- an invalid trial can never be the winner, so it can never open either
  gate — already true, and asserted so it stays true.
- the winner is resolved **once** for the launch decision; no second
  mutable best-trial score is introduced.
- the effective reference resolves per §16.C, so the gates are armed on a
  fresh chain instead of silently inert.

*Non-goals.* This commit does not touch formal-RESULT authority — §16.D
separates them. It does not change what the planner proposes, and it does
not change `force_formal_round`'s meaning.

*Dependencies.* Commit 5 (`D-C2b`) — the verdict must already be wired in production, not merely defined.

**3. Implementation plan.**
- [ ] Confirm by reading `:1480-1495` that the no-winner path is unchanged by commits 1–4.
- [ ] Add the assertion-level tests that the round still runs and is now labelled.
- [ ] If any earlier commit altered the path, **stop** and report before proceeding.

**4. Validation plan.**
- *Unit*: no-winner path still returns the planner's plan unchanged.
- *Integration*: a zero-valid-trial iteration completes, produces a record, and that record is non-authoritative.
- *Negative*: nothing raises; no iteration deadlocks (Stop Condition 2, §11).
- *Backward-compatibility*: the WARNING text is unchanged.
- *Real Gate*: none.

**5. Acceptance criteria.**
- [ ] With zero valid trials, `completed_rounds` is **unchanged** from pre-commit for the same inputs, a formal record exists, and it is non-authoritative.
- [ ] The `[STRATEGY]`/WARNING log lines are byte-identical.

**6. Failure and edge cases.** Deadlock → **stop for operator review**
(§11). Round cancelled instead of labelled → the commit has failed its own goal.

**7. Verification commands and evidence.**
```bash
./.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent/test_force_formal_round.py -q
```
- [ ] test count: __   - [ ] wall time: __   - [ ] focused pyright: __ errors

**8. Commit boundary.**
- [ ] Mostly tests; any production change here is a red flag to surface, not to absorb.

---

### Commit 7 — `D-C4`: incumbent exclusion

#### IMPLEMENTATION RECORD — D-C4 `[x]` COMPLETE

**Commit**: `<filled at commit>`, on top of the D-C3 reinforcement
`42a9f679`. Progress **6 / 10** once accepted.

**The rule**: only a formal record whose authority verdict is
`authoritative` may become the chain incumbent. Everything else stays
fully persisted and readable — the exclusion removes *comparison
authority*, not the record.

**Behavior Delta — present, and the largest in PR D so far.**

| record | before | after |
|---|---|---|
| authoritative, higher score | incumbent | incumbent (unchanged) |
| gate-invalid / diagnostic / observe-only / validity-unknown | **could become the incumbent** | excluded, reason logged |
| verdict edited after the fact | believed | refused |
| pre-declaration legacy artifact | **could become the incumbent** | excluded as `unreconstructable_legacy` |

The last row is the one to be aware of operationally: **a workspace whose
iterations predate D-C1a carries no incumbent forward.** That follows
directly from §12A — a record whose declared authority was never recorded
cannot have it reconstructed, and UNKNOWN is not a licence to assume. The
operator's rule is explicit: a high score, or having been the incumbent
under the old rules, does not confer authority.

**Production files changed**

| File | What |
|---|---|
| `core/scientific_authority.py` | `RecordAuthority` + `resolve_record_authority(...)` — fail-closed resolution for a PERSISTED record |
| `core/resume.py` | `_formal_candidate_is_authoritative(...)`, applied as an **additional conjunct** in the fold; `authority_basis` added to formal provenance |
| `agent/schemas/hyperparam_tuning.py` | `ExperimentRecord.scientific_authority` **declared** — see the defect below |

**The real producer → consumer path**

```text
tuner: final_record["scientific_authority"] = ScientificAuthority.from_context(...)   [D-C2b]
  → ExperimentRecord (NOW declared — was silently dropped, see below)
  → run_output_{iter}.json  all_records[]
  → core/resume.py incumbent fold
      → _formal_candidate_from_committed_fields | _candidates_from_persisted_verdicts
      → _formal_candidate_is_authoritative      ← D-C4's conjunct
          → resolve_record_authority(record, declared_*, commit_time_validity)
      → state.chain_best_valid_formal_score / _provenance
  → workflows/model_exploration.py → tuner input current_run_best_formal_score
  → the D-C3 launch gates
```

**A REAL DEFECT IN D-C2b, found here and fixed.** `ExperimentRecord`
declares no `extra` policy, so Pydantic's default `ignore` **silently
dropped `scientific_authority`** when `all_records` was validated into
`HyperparamTuningOutput`. D-C2b's verdict therefore never reached
`run_output_*.json` — the artifact resume actually reads. Verified by
execution: `model_validate({... "scientific_authority": {...}}).model_dump()`
did not contain the key. D-C4 cannot function without it, and D-C2b's
"tamper-evident, recomputable" property was unimplemented in the persisted
form.

This is the **third** instance in PR D of *emitted into a dict, never
declared on the schema* (after `formal_comparison_reference_source` and
its manifest hop). Filed as **FU-D-9** to add one cross-schema test that
every field the tuner writes into an output-bound dict is declared on the
receiving model — the per-field shape cannot express that rule.

The field is typed `dict[str, Any] | None`, deliberately, **not** the
model: `ScientificAuthority` sets `extra="forbid"` and exposes its
conclusions as computed fields, so its own dump cannot be re-validated
into it (verified — 5 validation errors). A plain dict is also what the
tamper-evidence design wants, since the consumer must re-derive rather
than trust.

**Design decisions, each evidence-determined**

1. **Consume, never re-derive.** `resolve_record_authority` calls
   `ScientificAuthority.from_context` and nothing else. A test asserts its
   source contains no `denoising_score`, `health_gate_results`,
   `_blocking`, `on_fail`, `resolved_action`, `is_trial` or `gate_name` —
   a second authority implementation is what the predecessor hotfix
   `af5339ce` existed to delete.
2. **The stored conclusions are never believed.** The returned `verdict`
   is always a fresh derivation; every conclusion key the stored block
   carries must equal it, or the record is refused as
   `verdict_inconsistent_with_its_facts`. Keys it does *not* carry are not
   compared, so an older verdict is not condemned for lacking a field that
   did not exist.
3. **A narrow fact-level cross-check, beyond the stated requirement.**
   Conclusion-vs-facts cannot catch a tamperer who edits the *facts*. So a
   stored `formal_validity: "valid"` contradicted by a commit-time
   **invalid** is refused (`stored_validity_contradicts_commit_time`).
   Deliberately scoped to that one weakening contradiction: commit-time
   **unknown** is an evidence gap, not a contradiction, and widening it
   would empty the incumbent for every workspace whose effective-policy
   artifact was merely lost. Both halves are tested.
   *Reachability note*: this check only bites on the **committed-fields**
   fast path, because the persisted-verdicts path already refuses an
   invalid record via the pre-existing commit-time conjunct. That makes
   "edit the committed `best_valid_formal_*` summary to promote an invalid
   record" the realistic attack it defends.
4. **Additional conjunct, not a replacement.** Commit-time validity still
   gates the candidate pool exactly as before; authority is applied on top.
5. **The tie rule is untouched** — strictly `>`, so earliest-iteration-wins
   still falls out of the ascending walk. Mutation C7 (`>` → `>=`) fails
   2 tests.
6. **Atomic provenance.** The predicate runs *before* the score/provenance
   assignment and both come from the same candidate record, so a refused
   record can never update the score while leaving another record's
   identity beside it.

**Tests** — the operator's 10-row matrix, all present, driving the real
`restore_prior_state` over on-disk workspaces:

| new formal | vs incumbent | expected | test |
|---|---|---|---|
| authoritative | higher | updates | `test_a_higher_authoritative_score_replaces_a_lower_one` |
| authoritative | equal | no update (strict `>`) | `test_an_equal_score_does_not_replace` |
| authoritative | lower | no update | `test_a_lower_authoritative_score_does_not_replace` |
| invalid, score 99 | higher | no update | `test_a_non_authoritative_record_never_becomes_the_incumbent` |
| diagnostic, score 99 | higher | no update | ″ |
| unknown, score 99 | higher | no update | ″ |
| verdict forged `true` | higher | refused by consistency | `test_a_tampered_verdict_is_refused_not_believed` |
| legacy, reconstructable | higher | updates | `test_a_legacy_record_under_a_declared_output_reconstructs` |
| legacy, unreconstructable | higher | no update | `test_an_undeclared_legacy_record_is_excluded` |
| high non-authoritative, then lower authoritative | — | the later one updates | `test_an_excluded_high_score_does_not_raise_the_bar_for_a_later_one` |

The last row is the one that matters most: incumbent 5.0 → diagnostic
100.0 → authoritative 6.0 must end at **6.0**. A refused record that
leaked into the comparison basis would freeze the chain at an unreachable
bar — worse than admitting it.

Plus `test_the_incumbent_identity_is_atomic_with_its_score`, the trial and
no-formal-record rows, and 20 unit tests for the typed boundary itself.

**Migrated fixtures.** `_write_iter` (`test_resume_incumbent.py`) and
`_p1_tune_output` (`test_run_one_iteration.py`) now declare the production
posture, because those tests are about the incumbent **walk** and
**manifest attribution** — tie rules, round provenance, repo-policy
isolation, artifact verification — not about authority. Without the
declaration every record in them is `unreconstructable_legacy` and the
behaviour under test never runs. The undeclared case is covered on purpose
in `TestScientificAuthorityAdmission`.

**Mutations — 8 run, 8 caught**

| # | mutation | caught by | n |
|---|---|---|---|
| C1 | admission predicate bypassed | the full matrix | 14 |
| C2 | trust the stored `authoritative` flag | tamper + per-conclusion cases | 6 |
| C3 | commit-time cross-check removed | both contradiction tests | 2 |
| C4 | legacy assumed authoritative | the undeclared-legacy rows | 6 |
| C5a | non-Mapping guard removed | malformed-verdict cases | 3 |
| C5b | validity vocabulary guard weakened | malformed `formal_validity` | 1 |
| C6 | schema drops the verdict again | the whole matrix | 11 |
| C7 | tie loosened `>` → `>=` | tie-earliest-wins + equal-score | 2 |

*Recorded honestly*: a first attempt at C5 (`return` → `stored = {}`) was
an **equivalent mutant** — the next guard catches it — and survived. It
was replaced with two mutations that genuinely change behaviour rather
than being reported as a coverage gap.

**Validation**

| Check | Result |
|---|---|
| `test_resume_incumbent.py` | 39 passed, 1.1 s |
| `test_scientific_authority.py` | 49 passed, 0.1 s |
| core + agent + sdsc + execute_tools | 6384 passed, 400 s |
| full `tests/unit` | 7469 passed, 2 skipped, 4 xfailed, **3 failed** — all three PRE-EXISTING and unrelated; see below |
| pyright | **0 errors**, 4 warnings (pre-existing) |
| ruff / ruff format | clean |

> **THE BRANCH IS NOT FULLY GREEN, and this checkpoint did not make it
> red.** Three tests fail in
> `tests/unit/sdsc_submission_scripts/test_v19_queue_runner.py`
> (`TestTheLiveProcessGuardExcludesOnlyItself`): the three cases asserting
> the guard SHOULD block. The guard is silent, the launch proceeds, and
> the log reads `screen did not start`.
>
> **Proved pre-existing, not assumed.** `git archive` exports of
> `42a9f679` (D-C3 reinforcement) and `8985d00f` (before D-C3) were run
> from clean temporary trees with none of the D-C4 changes present: both
> reproduce the same three failures. They also reproduce 3/3 in isolation,
> which rules out test-order pollution. D-C4 touches no shell script and
> no queue-runner test.
>
> **What was ruled out**: `ps -eo args` truncation (a 156-char argv, the
> realistic length, is shown in full), leaked `screen` sessions (only the
> operator's own 07/31 monitor is present), and
> `RUNNER_BASENAME` being derived from `$0` (it correctly uses
> `${BASH_SOURCE[0]##*/}`). The cause is not yet identified; the tests
> passed on this same box in two full-suite runs earlier the same day,
> which points at an environment-sensitive process-scan rather than a code
> change. Sourcing the runner to instrument it is refused by the repo's
> own launch guard, so the next step needs a different probe.
>
> Filed as **FU-D-10**, owned by PR E's guard work. It must be resolved
> before this PR can merge — which is not yet authorized in any case.

**Follow-ups**

- **FU-D-10** `[x]` **CLOSED** — merged to master as PR #172
  (`775f0df8` + `36ecc5b1`, merge `51bab481`). Not a PR D regression and
  not a test flake: the live-process guard **failed OPEN** because
  `grep -q` closed the pipe early and `pipefail` turned the upstream
  SIGPIPE into a non-zero pipeline. Load-dependent, so it failed exactly
  when the machine was busy. Integrated into this branch at `12506d80`.
- **FU-D-9** `[x]` **CLOSED** — see the reinforcement record below.
- ~~**FU-D-7**~~ — **WITHDRAWN 2026-08-05** with the rest of the legacy
  reconstruction scope. Historical artifacts are neither annotated nor
  reinterpreted; a null `formal_comparison_reference_source` simply means
  authority is not established.

---

#### REINFORCEMENT — the 249-artifact audit, FU-D-9, and the scope correction

**Commit**: `<filled at commit>`. Still checkpoint **D-C4**; acceptance
makes progress **6 / 10**.

**1. The legacy audit that forced the scope correction.**

Read-only over 249 real artifacts in `/home/klz/Data/SIDEREIS_DATA`:

| fact | recoverable? | evidence |
|---|---|---|
| `healthgate_mode` | **absent 249/249**; derivable from a sha-pinned effective config | 42 artifacts stamp a sha; all 42 have a recoverable config; the 4 distinct configs resolve to 1 blocking / 3 observe-only |
| `result_authority` | **absent 249/249, and derivable from nothing** | not in any output, not in `run_invariants_lock.json`, not in any manifest |
| formal HealthGate validity | recoverable where the config is | `_classify_commit_time` against the sha-pinned effective config |

`authoritative` requires `scientific`. `scientific` is recoverable from
nothing, so **no historical record can reconstruct to authoritative** —
and inferring it from a blocking configuration would invent a declaration
nobody made, which is what D-C1b refuses at launch.

The operator's ruling (2026-08-05) therefore **withdrew** observe-only and
blocking reconstruction, the `operator_legacy_declaration` sidecar
boundary, and D-C9 in full. §15.E is corrected accordingly.

**No implementation change was required.** `eb789271` already returns
`unreconstructable_legacy` for every record lacking the D-C1a fields,
which is exactly the ruled behaviour. The audit is retained as the
*evidence for why the rule is right*, not as a reconstruction spec.

**2. FU-D-9 — producer-to-artifact transport.**

`tests/unit/agent/schemas/test_producer_to_artifact_transport.py` (6
tests). Kept separate from `test_cross_schema_invariants.py`, whose remit
is *declaration consistency across models*; this is *runtime transport to
artifacts*, a different rule class, and the filename says so.

It validates **transport, not declaration**. Introspecting `model_fields`
would pass for a field that is declared and then dropped at a later hop —
which is the `write_manifest` defect exactly. So values are pushed through
the real production boundaries and read back out of the real artifact:

```text
producer dict → HyperparamTuningOutput.model_validate
              → model_dump_json → run_output_*.json   (what resume reads)
              → write_manifest  → manifest.json        (the second hop)
```

Four channels at two nesting levels, which is what made the defects
invisible:

| field | boundary that dropped it |
|---|---|
| `healthgate_mode` | output schema |
| `result_authority` | output schema |
| `formal_comparison_reference_source` | output schema, **then again** at `write_manifest` |
| `scientific_authority` | `ExperimentRecord`, nested inside `all_records` |

Plus one test asserting a **single artifact carries all four** — a
per-field test cannot catch a boundary that drops a *different* field,
which is how three instances each passed review.

**Mutations — 4 run, 4 caught**, each a faithful reproduction of a real
defect: output drops the reference source (3 failing); `ExperimentRecord`
drops `scientific_authority` (2); output drops `healthgate_mode` (2);
`write_manifest` drops the reference source (1).

**Next checkpoint**: D-C5 — aggregation and report exclusion, stated
deterministically rather than left to the LLM.

---

**1. Goal.** The first commit that changes a decision. Isolated so it can be
reverted without touching reporting.

**2. Scope.** `core/resume.py` — **extend** the commit-time-validity
predicate for `chain_best_valid_formal_*` (`:200-215`), do not replace it.

*Non-goals.* The commit-time-validity rule and its "repo-current config is
NEVER consulted" guarantee (`:306-310`) must survive untouched.

*Dependencies.* Commit 5 (`D-C2b`) — the consumer needs a verdict that production actually attaches.

**3. Implementation plan.**
- [ ] Read `:196-320` fully before editing.
- [ ] Add `enters_incumbent_selection` as an **additional** conjunct.
- [ ] Handle records predating the field by **deterministic reconstruction first**, not blanket exclusion. The draft said "legacy ⇒ UNKNOWN ⇒ excluded" while also promising replay parity — and since EVERY historical record lacks the fields, those two cannot both hold. Ladder:
  1. reconstruct from what old records already persist — `best_valid_trial_*`, the formal record's own gate validity, and the config provenance (`health_checks_config`, `health_config_sha256`);
  2. if reconstruction is complete, emit a `reconstructed_legacy` verdict — **without writing anything back to the artifact** (§4.5);
  3. only if it cannot be reconstructed is it `legacy_authority_unknown`, and excluded.
- [ ] This preserves history untouched and avoids emptying every historical incumbent at once.
- [ ] Extend `validity_basis` provenance so an exclusion is auditable.

**4. Validation plan.**
- *Unit*: zero-valid-trial formal excluded; valid one still selected; a legacy record with enough provenance reconstructs to `reconstructed_legacy`; one without it is `legacy_authority_unknown` and excluded.
- *Integration*: a multi-iteration chain picks the same incumbent as before when all results are authoritative — **default parity**.
- *Negative*: no record ⇒ `None`, never a fabricated incumbent.
- *Backward-compatibility*: replaying an existing chain workspace yields the **same incumbent** wherever reconstruction succeeds. A difference may arise only where a zero-valid-trial result was previously selected — that difference is the fix, and is recorded with the reconstruction basis.
- *Real Gate*: none.

**5. Acceptance criteria.**
- [ ] On a fixture chain where iteration N had zero valid trials and the best score, the incumbent after this commit is iteration M ≠ N, and `chain_best_valid_formal_provenance` names the exclusion basis.
- [ ] On an all-authoritative fixture, the selected `exp_id` and score are **identical** to pre-commit.

**6. Failure and edge cases.**
| case | behaviour |
|---|---|
| every candidate excluded | incumbent `None` — legitimate, not an error |
| legacy records, reconstructable | `reconstructed_legacy`; artifact untouched |
| legacy records, not reconstructable | `legacy_authority_unknown` ⇒ excluded; **warn** so it is visible |
| verdict disagrees with commit-time validity | both must pass; neither overrides the other |

**7. Verification commands and evidence.**
```bash
./.venv/bin/python -m pytest tests/unit/core/test_resume_incumbent.py -q
./.venv/bin/python -m pytest tests/unit/core/ -q -k resume
```
- [ ] test count: __   - [ ] wall time: __   - [ ] focused pyright: __ errors

**8. Commit boundary.**
- [ ] Reviewable as one predicate extension.
- [ ] Before committing: show that the commit-time-validity logic is unmodified in the diff.

---

### Commit 8 — `D-C5`: aggregation and report exclusion, stated not silent

#### IMPLEMENTATION RECORD — D-C5 `[x]` COMPLETE

**Commit**: `<filled at commit>`, on top of D-C4 `7a128f18`. Progress
**7 / 10**.

**Behavior Delta**: a non-authoritative formal score no longer enters the
scientific aggregate, and the exclusion is stated rather than silent.

**The named contract in this section was confirmed against master and
implemented as specified** — `execute_tools/scientific_aggregation.py`,
`AggregationScope(included / excluded / excluded_count / all_excluded)`.
Two additions the audit showed were needed: `no_records` (distinct from
`all_excluded`) and `exclusion_reason_counts` (grouped and order-stable,
so a rendered report diff shows real change rather than dict ordering).

**Production files changed**

| File | What |
|---|---|
| `execute_tools/scientific_aggregation.py` | **new** — `AggregationScope`, `ExcludedResult`, `partition_for_aggregation`, `provenance_lines()` |
| `agent/schemas/interpretation.py` | `ModelRunSummary.scientific_authority`; `InterpretationOutput.scientific_aggregation` |
| `nodes/result_interpretation_agent/result_interpretation_agent.py` | producer attaches the formal record's verdict; `run()` partitions before any LLM call and filters `per_model_formal`; both output-assembly sites carry the scope |

**The real producer → consumer path**

```text
tuner: final_record["scientific_authority"]                    [D-C2b]
  → ExperimentRecord                                           [D-C4]
  → run_output_*.json
  → tuning_output_to_model_run_summary()
      → ModelRunSummary.scientific_authority   (the SAME formal record
        `formal_score` came from, so score and authority cannot describe
        different experiments)
  → ResultInterpretationAgent.run()
      → partition_for_aggregation(inp.summaries)   ← BEFORE any LLM call
      → per_model_formal filtered to authoritative only
          → _build_synthesis_prompt(per_model_formal=…)   ← the LLM sees
            only authoritative formal scores
      → InterpretationOutput.scientific_aggregation (both healthy AND
        degraded assembly, so an interpreter LLM failure cannot lose the
        provenance — the rule the health evidence already follows)
```

**§4.7 satisfied, and the preferred branch taken.** The exclusion is
derived deterministically and rendered from the typed object; **no
exclusion text is placed in any prompt.** Both reasons in §4.7 hold: a
model may simply not mention the exclusion, and exclusion text inside a
prompt can steer the interpretation it then writes.

**D-C5 IS LLM-AFFECTING, and the design's "non-LLM-facing" note is
narrower than it reads.** Filtering `per_model_formal` necessarily changes
the synthesis prompt's content — that is the point of the checkpoint. What
§4.7 forbids is routing the *exclusion report* through the model, and that
is honoured. Recorded here because it sets the Gate 1 scope: D-C5 alters
LLM-visible aggregate facts, so the single bounded Gate 1 run after D-C6 /
D-C7b must cover it.

**Authority is consumed, never re-derived.** A test asserts
`partition_for_aggregation`'s source contains no `denoising_score`,
`formal_score`, `health_gate_results`, `_blocking`, `on_fail`,
`resolved_action` or `gate_name`, and does call
`resolve_record_authority`. Tampered and malformed verdicts fail closed
through the same D-C4 resolver.

**Task-generic**: the boundary consumes a structural protocol
(`model_type` + `scientific_authority`), not `ModelRunSummary`, and names
no task, model or metric.

**Tests** — 21 in `tests/unit/execute_tools/test_scientific_aggregation.py`
plus 5 reachability tests in the interpretation-agent suite. The operator's
matrix, all covered: authoritative included; invalid / diagnostic /
unknown / observe-only high scorers excluded with their reasons; mixed;
all-excluded; no-records; ordering and counts ignore excluded records;
excluded retained with reasons; tampered and malformed fail closed.

**Mutations — 6 run, 6 caught.**

| # | mutation | caught by | n |
|---|---|---|---|
| A1 | agent stops filtering the aggregate | `test_an_excluded_formal_score_never_reaches_the_synthesis_prompt` | 1 |
| A2 | summary drops the verdict | producer reachability test | 1 |
| A3 | non-authoritative treated as included | the matrix | 19 |
| A4 | `all_excluded` collapses to `no_records` | stated-outcome + provenance tests | 2 |
| A5 | excluded results are dropped | the matrix | 18 |
| A6 | provenance omits the reasons | the rendering test | 1 |

> **A1 SURVIVED on the first run — a genuine coverage gap, not an
> equivalent mutant, and worth recording.** The reachability tests
> asserted the typed scope reached the output but never that the excluded
> score stayed out of the *prompt*. The fixture also set
> `best_denoising_score == formal_score`, and the renderer emits a
> "Formal score" line only when the two DIFFER — so removing the filter
> changed nothing observable. Closed by a test that captures the real
> synthesis prompt with deliberately unequal scores. The same shape as the
> D-C4 equivalent-mutant note: a mutation that survives is either a gap or
> a bad mutation, and the two must be told apart rather than assumed.

**Validation**

| Check | Result |
|---|---|
| `test_scientific_aggregation.py` | 21 passed |
| interpretation-agent suite | 256 passed |
| `tests/unit/agent` + `execute_tools` + `core` | 5968 passed, 277 s |
| pyright | **0 errors**, 4 warnings (pre-existing) |
| ruff / format | clean, 725 files |

**Next checkpoint**: D-C6 — structured all-trials-invalid planner feedback.

---

**1. Goal.** Non-authoritative results leave scientific aggregation, **and
the exclusion is visible**. Separate from commit 6 because it changes what a
human reads rather than what the chain decides.

**2. Scope.** `nodes/result_interpretation_agent/result_interpretation_agent.py`
summary consumption (`:911`, `:924`, `:961`, `:1272`) and the report path.

*Non-goals.* No change to the frozen TIDMAD score formula. No change to how
a score is computed — only to which scores are aggregated.

*Dependencies.* Commit 4 (`D-C2b`) — renumbered 2026-08-05.

> **The report layer does not exist — this commit CREATES it.**
> The post-PR-E re-audit answered the open question (§15.D): there is no
> report-assembly module outside the interpretation agent. `execute_tools/`
> has none, and the only report-shaped code is
> `core/runtime_control/gpu_measurement_*` and
> `scripts/official_paper_health_scan.py`, neither of which assembles
> campaign results. So this commit cannot be written as "filter the
> existing report path".
>
> **Named contract**, to be confirmed against master at implementation
> time rather than assumed now:
>
> ```text
> module   execute_tools/scientific_aggregation.py        (new)
> input    list of summary records carrying ScientificAuthority
> output   AggregationScope(
>              included:        list[record],
>              excluded:        list[(record_id, typed_reason)],
>              excluded_count:  int,
>              all_excluded:    bool,
>          )
> ```
>
> The interpretation agent consumes `included`; the deterministic
> provenance section renders `excluded` and `excluded_count` from the same
> typed object. **No model involvement**, so §4.7's ruling holds and this
> stays non-LLM-facing.
>
> `all_excluded` is explicit because "every result was excluded" must read
> as a stated outcome, never as an empty aggregate that looks like a
> successful campaign with no findings.

**3. Implementation plan.**
- [ ] Read each of the four `inp.summaries` loops before editing; they are not obviously equivalent and may need different handling.
- [ ] Create the aggregation module above; it owns the include/exclude decision, and the agent consumes its output.
- [ ] Filter on `enters_scientific_aggregation`.
- [ ] Emit an explicit "N results excluded as non-authoritative, because …" line — a silently smaller sample is the failure mode being prevented.
- [ ] Render the exclusion deterministically from the typed object; **no LLM-facing input**. If implementation shows that is impossible, **stop for separate approval** rather than routing it through the model.

**4. Validation plan.**
- *Unit*: excluded results absent from aggregation; the count is reported.
- *Integration / pseudo*: a mixed run reports both the aggregate and the exclusion.
- *Negative*: **all** results non-authoritative ⇒ empty aggregate **plus** an explicit statement — never a blank section (Stop Condition 3, §11).
- *Backward-compatibility*: an all-authoritative run's aggregate is numerically identical to pre-commit.
- *Real Gate*: none.

**5. Acceptance criteria.**
- [ ] For an all-authoritative fixture, the aggregate value is **bit-identical** to pre-commit.
- [ ] For a mixed fixture, the aggregate excludes the non-authoritative records **and** the report contains the count and per-reason breakdown, rendered deterministically — verified by asserting the exact text, not by a model producing it.
- [ ] For an all-non-authoritative fixture, the output says so explicitly rather than rendering an empty aggregate.

**6. Failure and edge cases.** Empty report → **stop for operator review**
(§11): §20.6 is right that this indicates a deeper problem than gate policy.
Field absent on legacy summaries → treat as UNKNOWN and **warn**.

**7. Verification commands and evidence.**
```bash
./.venv/bin/python -m pytest tests/unit/agent/result_interpretation_agent/ -q
```
- [ ] test count: __   - [ ] wall time: __   - [ ] focused pyright: __ errors

**8. Commit boundary.**
- [ ] If the exclusion must appear in an LLM prompt, that part is **split out** and separately approved.

---

### Commit 9 — `D-C6`: structured all-trials-invalid feedback

#### IMPLEMENTATION RECORD — D-C6 `[x]` COMPLETE

**Commit**: `<filled at commit>`, on top of D-C5 `4767c72a`. Progress
**8 / 10**.

**DEVIATION, and the audit that forced it: a NEW carrier, not an extension
of `GateExhaustionInfo`.** This section instructed extending
`_build_gate_exhaustion` (§3.8) while also instructing "confirm it is the
right carrier before extending it". The audit says it is not:

| | `GateExhaustionInfo` | all-trials-invalid |
|---|---|---|
| trigger A | no record succeeded **and** ≥1 `skipped_oom_risk`/`skipped_time_risk` | records DID succeed |
| trigger B | fail-round burst ≥50% budget-gated | no budget gating at all |
| meaning | the architecture is too heavy for the budgets | the architecture collapses |
| planner response | propose something **lighter** | propose something that does not **collapse** |

Neither trigger fires for an all-invalid iteration, so extending it would
have meant a third trigger with unrelated semantics inside a structure
whose every field means "budget exhaustion" — merging two failure modes
that call for opposite responses. Proven by execution in
`test_the_carrier_is_not_gate_exhaustion`, which asserts
`_build_gate_exhaustion` returns `None` for exactly this input.

The new carrier mirrors the existing channel exactly rather than inventing
a mechanism, so §3.8's real intent ("no second ad-hoc feedback path") is
honoured.

**Production files changed**

| File | What |
|---|---|
| `agent/schemas/health_feedback.py` | **new** `TrialValidityFeedback`, `InvalidTrialOutcome` |
| `agent/schemas/hyperparam_tuning.py` | `HyperparamTuningOutput.trial_validity_feedback` |
| `nodes/.../ml_hyperparameter_tune_agent.py` | `_build_trial_validity_feedback`; `_skipped_formal_for_no_valid_winner` set AT the skip gate |
| `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py` | collects the window |
| `agent/schemas/proposal.py` | `ProposalInput.recent_trial_validity` |
| `nodes/.../ml_model_proposal_agent.py` | `_format_recent_trial_validity_block` + prompt variable |
| `agent/prompt_templates/proposal/proposing_stage.md` | `{recent_trial_validity_block}` |

**The real producer → consumer path** (every hop mutation-proven)

```text
trial records + gate verdicts
  → _build_trial_validity_feedback(...)          [tuner, at run exit]
  → HyperparamTuningOutput.trial_validity_feedback
  → run_output_*.json
  → ml_result_interp_to_ml_model_propose         [protocol, sparse window]
  → ProposalInput.recent_trial_validity
  → _format_recent_trial_validity_block(...)
  → {recent_trial_validity_block}                [proposing_stage.md]
  → the ACTUAL next planner request
```

**The distinctions are preserved, which is the checkpoint's point.**
Execution failure (evidence *absent*) ≠ gate invalidity (evidence
*negative*) ≠ validity unknown (gates could not judge) ≠ formal skipped
for no winner ≠ formal skipped on budget (a different carrier) ≠ formal
result invalidity (D-C2b). `_skipped_formal_for_no_valid_winner` is set
where the decision is MADE, because inferring it later from a missing
formal record cannot distinguish a no-winner skip from a budget skip.

**Task-generic.** Gate names, reasons and metrics pass through exactly as
the gate system recorded them; the block prescribes no remedy. A test
asserts the builder's source contains no task names or advice verbs, and
another asserts the rendered block contains no recommendation language —
what a mode fraction implies is the planner's judgement, and baked-in
advice would be wrong for the next task anyway.

**Backward compatibility.** `None` whenever any trial is valid, so the
window stays empty and the prompt block collapses to `""` — a healthy
chain's proposer prompt is byte-identical to before.

**Beyond the plan**: `evidence_absent` now also names a PARTIAL gate set,
not just a wholly missing one. Found by execution — a record with one of
three blocking gates classifies as UNKNOWN, and an unnamed partial set
reads exactly like a pass.

**Mutations — 7 run, 7 caught**: fires on healthy runs (1); execution
failure merged into invalidity (2); skip reason never set (1); protocol
stops forwarding (1); prompt variable dropped (1); template placeholder
removed (1); absent evidence silenced (2).

**Validation**: 24 focused tests; `tests/unit/agent` + `core` +
`execute_tools` **5992 passed**, 278 s; pyright **0 errors**; ruff and
format clean (726 files).

**Gate 1 is REQUIRED and still pending** — this changes LLM-visible input.
Deferred to one bounded combined run after D-C7b, per the plan, so the
Gate proves the FINAL prompt rather than an intermediate one. D-C5's
aggregate change is in the same scope.

---


**1. Goal.** Close D6 by extending the existing gate-exhaustion block rather
than opening a second feedback channel (§3.8).

**2. Scope.** `_build_gate_exhaustion` and its call site (`:5279-5290`), and
the feedback schema it populates.

**This commit IS an LLM-facing change, and Gate 1 applies** (operator,
2026-08-04). Its acceptance criterion is that the feedback *reaches the next
iteration's planner input* — that is a change to LLM-facing input whether or
not any natural-language prompt text is edited. The draft's "no prompt-text
change ⇒ no separate approval" was wrong.

*Non-goals.* No new feedback channel; the existing gate-exhaustion block is
extended.

*Dependencies.* Commit 5 (`D-C2b`).

**3. Implementation plan.**
- [ ] Read `_build_gate_exhaustion` and its schema fully; confirm it is the right carrier before extending it.
- [ ] Add the all-trials-invalid evidence to the existing structure.
- [ ] Determine whether any prompt text changes; if yes, **stop and split**.

**4. Validation plan.**
- *Unit*: the block is populated when zero trials are valid, absent otherwise.
- *Integration / pseudo*: it reaches the next iteration's planner input.
- *Negative*: a run with valid trials is unchanged.
- *Backward-compatibility*: the existing gate-exhaustion trigger behaviour is unaltered.
- *Real Gate*: **Gate 1 REQUIRED** — this commit changes LLM-facing input.
  Listed separately and **not launched without operator approval**.

**5. Acceptance criteria.**
- [ ] The structured feedback is proven to reach the **real** planner path, not merely to be constructed.
- [ ] A mutation removing the field **fails Gate 1**.
- [ ] The agent/node/skill schema docs are updated in the same change.
- [ ] With zero valid trials the feedback names the count, the gates that failed, and the mode.
- [ ] With ≥1 valid trial the feedback is **byte-identical** to pre-commit.

**6. Failure and edge cases.** Missing gate results → include what exists,
mark the rest absent; never fabricate. Feedback disabled by policy →
respect the existing `health_feedback_policy`.

**7. Verification commands and evidence.**
```bash
./.venv/bin/python -m pytest tests/unit/agent/schemas/test_health_feedback.py -q
```
- [ ] test count: __   - [ ] wall time: __   - [ ] focused pyright: __ errors

**8. Commit boundary.**
- [ ] LLM-facing by nature: Gate 1 is required and its approval recorded before merge.

---

### Commit 10 — `D-C7b`: five fields recorded per gate; the operator-facing label stops lying

#### IMPLEMENTATION RECORD — D-C7b `[x]` COMPLETE

**Commit**: `<filled at commit>`, on top of D-C6 `3e91adb6`. Progress
**9 / 10**.

**Behavior Delta**: gate results now say what the gate WAS, not what its id
is spelled like. No decision changes — this is the labelling checkpoint.

**The preferred outcome was achieved: NO config file was touched**, so
`health_config_sha256` is unshifted. Verified against the audited values —
`configs/health_checks.yaml` → `3b552118…`, the observe config →
`d133a12d…`, exactly the shas in the compatibility map. No workspace
invariant lock crosses a boundary, and the acceptance criterion "zero
changes to any gate id string" holds: `git diff` touches no config and no
id, the only occurrence being a docstring quoting one as an example.

**What was already there, confirmed before adding anything** (the design
asked): `gate_name` IS the stable `gate_id`; `resolved_action` IS the
effective action. Added beside them: `gate_role`, `configured_action`,
`healthgate_mode`, `result_authority`, plus a derived `display_label`.

**Why `configured_action` is not redundant with `resolved_action`**:
`resolved_action: continue` is ambiguous on its own — it means either
"the check passed, so nothing to do" or "configured to do nothing". Only
both together separate them, and that ambiguity is what let a
`_blocking`-named gate read as enforcing when it enforced nothing.

**The label is derived, never read from the id.** A gate whose configured
action cannot invalidate reads `observational` however it is spelled; one
that can reads `enforcing`; one whose posture cannot be established reads
`role-unknown` rather than defaulting. Ids are never rewritten — they are
the join key for `health_gate_results` and archived artifacts.

| id | configured action | label |
|---|---|---|
| `output_diversity_blocking` | `continue` | `output_diversity_blocking (observational)` |
| `output_diversity_blocking` | `invalidate_round` | `output_diversity_blocking (enforcing)` |
| `legacy_blocking` | absent | `legacy_blocking (role-unknown)` |

**Backward compatibility**: every new field is optional, so an archived
result parses unchanged and joins by `gate_id` exactly as before.

**Mutations — 5 run, 5 caught, but two only after fixing real problems the
first pass exposed:**

| # | mutation | outcome |
|---|---|---|
| C1 | label read from the id suffix | caught (5) |
| C2 | unknown role defaults to enforcing | **survived** — the guard was a REDUNDANT branch producing identical output. Removed the redundancy; the re-run mutation is caught |
| C3 | producer stops recording `configured_action` | caught (1) |
| C4 | role inferred instead of read | caught (1) |
| C5 | tuner stops supplying the declaration | **survived** — a REAL coverage gap: the asserted string occurs three times in `run()` (D-C2b, D-C6, here), so deleting one still passed. Re-pointed at the gate-evaluation call site specifically; now caught |

C5 is the more instructive of the two. A structural assertion that searches
a 2,000-line function for a string is only as strong as that string's
uniqueness, and this one had stopped being unique two checkpoints earlier.
Fixing it also required a bounded window rather than a regex, because the
call contains a nested `os.path.join(...)` and a non-greedy match silently
truncated the body at the wrong closing paren.

**Validation**: 17 focused tests; `tests/unit/execute_tools` + `agent` +
`core` **6009 passed**, 286 s; pyright **0 errors**; ruff and format clean
(727 files).

---


**1. Goal.** Close D-D-3 and §3.2. Last among behavioural commits because it
is cosmetic in effect and must not be confused with the authority work.

**2. Scope.** The gate entry model (`execute_tools/health_checks/config.py:82+`)
gains a declared `role`; `configs/health_checks.yaml` and
`configs/health_checks_baseline_observe_mode.yaml` declare it.

*Non-goals.* **Gate ids are NOT renamed** — they are join keys in
`health_gate_results` and historical artifacts, and renaming would break
artifact comparison. The role is added beside the id.

*Dependencies.* None strictly; sequenced last deliberately.

**3. Implementation plan.**
- [ ] Record five fields together on every new gate result and operator-facing report: `gate_id` (stable, **never rewritten**), `configured_action`, `effective_action`, `healthgate_mode`, `result_authority`.
- [ ] Confirm `configured_action` / `effective_action` are already derivable from the existing gate-result structure before adding anything new — the counterfactual field already exists (§3.3), so check whether these do too.
- [ ] Add an operator-facing **display label** derived from `effective_action`, so a gate resolving `continue` is never displayed as blocking. The id keeps its historical spelling as a compatibility identifier.
- [ ] Do **not** modify any gate id, in configs, code or fixtures.
- [ ] Confirm `core/campaign_artifacts.py:49-53` still passes (FU-D-1: it deliberately requires observe behaviour for baseline artifacts).

**4. Validation plan.**
- *Unit*: all five fields present on a new gate result; the display label of a `continue`-resolving gate does not contain "blocking"; historical ids unchanged.
- *Backward-compatibility*: if any config file changes, `health_config_sha256` shifts — verify no invariant lock compares across the boundary and record the expected change. **If the five fields can be recorded without touching the config files, the sha256 must NOT change**, and that is the preferred outcome.
- *Negative*: unknown role rejected.
- *Real Gate*: none.

**5. Acceptance criteria.**
- [ ] `git diff` shows **zero** changes to any gate id string, in configs, code or fixtures.
- [ ] For `configs/health_checks_baseline_observe_mode.yaml`, every gate result carries `configured_action: continue`, `effective_action: continue`, and a display label containing no form of the word "blocking".
- [ ] An archived V19 artifact still joins by `gate_id` without modification.
- [ ] `core/campaign_artifacts.py` validation still passes on an existing baseline artifact.

**6. Failure and edge cases.** Historical artifact joined by id → unaffected,
because ids are unchanged. `health_config_sha256` shift → expected and
recorded; if any lock compares across it, **stop**.

**7. Verification commands and evidence.**
```bash
./.venv/bin/python -m pytest tests/unit/execute_tools/ -q -k health
./.venv/bin/python -m pytest tests/unit/core/test_campaign_artifacts.py -q
```
- [ ] test count: __   - [ ] wall time: __   - [ ] focused pyright: __ errors

**8. Commit boundary.**
- [ ] Labels only; no authority logic in the diff.

---

### ~~Commit 11~~ — `D-C9`: **WITHDRAWN — operator decision 2026-08-05**

The V19 closure annotation, its schema/generator, and the sidecar evidence
step are **removed from PR D's scope entirely**. So is every form of
historical authority reconstruction and the
`operator_legacy_declaration` boundary that an earlier revision of this
document proposed.

**The single rule for historical records now reads:**

```text
missing the new authority contract
  -> remains readable
  -> remains unchanged
  -> scientific authority is NOT established
  -> never becomes the new-authority incumbent
  -> never enters new-authority scientific aggregation
```

No finer classification of historical records is required or wanted. The
249-artifact audit recorded under D-C4 is retained as the *evidence for
why* this rule is correct — `result_authority` was never persisted by any
historical run and therefore cannot be recovered — not as a specification
for reconstructing anything.

PR D is therefore a **10-checkpoint** PR. The full text of the withdrawn
commit is preserved in Git history at `eb789271`.

---

### After the last commit — `D-C8` doc sync

Per the repository rule, doc sync is the **final step before merge**,
written against merged code, with each documented flag and default quoted
back against the source. Operator requirement 2026-08-04: **all affected
skill, node, agent, launcher, CLI and example `.md` files are updated in the
same change** — `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md`,
`docs/design/pluggable_health_checks.md`, the launcher docs under
`sdsc_submission_scripts/`, `docs/running_chain_test.md`, and this
document's checkpoint tracker moved to `[x]` with recorded evidence.

## 8. Genericization impact (§1.4.5)

| # | Question | Answer |
|---|---|---|
| 1 | What does this PR hardcode? | Nothing new. The mode vocabulary is orchestration policy, not task science. |
| 2 | Task-specific logic in generic code? | **No — and this is the PR's main genericization risk.** `unique_int8 > 25` and amplitude collapse are denoising-specific and **stay in `configs/health_checks.yaml`**. PR D must not make the orchestrator formal-aware *about thresholds*. |
| 3 | Generic/task split | Generic owns: blocking-vs-observational, authoritative-vs-not, ordering, severity resolution, control-flow consequences. Task owns: what collapse is, the metrics, the thresholds, what a valid result is. Straight from §20.6. |
| 4 | Config hierarchy | Mode is campaign-level; thresholds stay task-level. A spectroscopy task would supply different checks and reuse this orchestration unchanged. |
| 5 | Deferred? | Gate id naming (`*_blocking`) is task-neutral but historically loaded — D-D-3 prefers a declared role over a rename, to preserve artifact joins. |
| 6 | In-passing refactor | The authority verdict is the seam. It replaces an implicit "a record is a result" assumption spread across incumbent and reporting. |
| 7 | What must NOT move | Every scientific threshold. The frozen TIDMAD score formula. `GateAction` severity resolution. |

---

## 9. Validation

Layers follow the PR B/PR C convention.

**Layer 1 — unit.** Mode validation; mode↔config mismatch rejection; the
authority verdict across every basis; `enters_*` consequences derived, never
independently settable; zero/one/mixed valid-trial counting.

**Layer 2 — integration, no GPU.** Blocking mode; observe-only mode;
zero-valid-trial; one-valid-trial; mixed valid/invalid; diagnostic formal;
incumbent exclusion; reporting exclusion; manifest provenance. All nine are
§20.6's validation list.

**Layer 3 — bounded real run.** §20.6 requires a small real run that
**deliberately produces collapse** and proves the formal result cannot become
authoritative. Run it in a **fresh workspace** with a bounded
collapse-inducing configuration of the same class as V19's. **V19's
artifacts are a read-only reference for the expected signature — never a run
input** (§4.5); feeding them in would both contaminate the run and put the
immutable archive on a write path.

**Reachability evidence is mandatory** (PR C's lesson, twice over): a test
that fails when the production path bypasses the verdict. PR C shipped an
identity adapter reading two keys that were never written, and a replay
passed because it hand-fed the value. The equivalent failure here — a
verdict computed and never consulted — must fail a test.

---

## 10. Merge criteria

From §20.6, plus what the audit added:

1. campaign mode is explicit **and verified against the resolved config**;
2. no authoritative result exists without a valid trial;
3. observe-only remains available, unchanged in behaviour, and honest;
4. labels do not contradict effective behaviour (§3.2 is fixed);
5. incumbent and reports enforce the policy;
6. no scientific threshold moved into orchestration code;
7. exclusions are **stated**, never silent.

---

## 11. Stop conditions

Stop for operator review if:

* the blocking config would invalidate rounds that are **scientifically
  legitimate on some band** — the `any_pass` aggregation over files
  `[3, 10, 17]` exists precisely because bands differ, and a band-legitimate
  round being invalidated is evidence the threshold, not the policy, is
  wrong;
* zero-valid-trial handling would **deadlock** an iteration with no path
  forward (D-D-1 is designed to prevent this; if it does not, stop);
* excluding non-authoritative results **empties the report entirely** —
  §20.6 is right that this indicates a deeper problem than gate policy;
* the mode↔config check would reject a **historical** workspace on resume,
  which would make old evidence unreadable.

---

## 12. Follow-ups filed, not fixed here

| ID | Finding |
|---|---|
| **FU-D-1** | `core/campaign_artifacts.py:49-53` hardcodes observe-only expectations for baseline artifacts (§3.7). Correct today; revisit if baselines ever run blocking. |
| **FU-D-2** | `best_valid_trial_*` (`:5332-5336`) persisted since V19 and consumed by nothing. D-C2b gives them a consumer; if it does not, they should be removed rather than left as decoration. |
| **FU-D-3** | Two notions of trial validity coexist (`:5266-5269` bookkeeping vs `_best_trial_winner`'s predicate requiring `memory.time_mode == "trial"`). PR D uses the bookkeeping one; the divergence should be resolved or documented as intentional. |
| **FU-D-4** | `Best score: None` reporting clarity (§3.8). |
| **FU-D-5** | `ci.yml:43` names the step "pyright (strict, blocking)" while `pyrightconfig.json` sets `typeCheckingMode: "basic"`. Either the name or the mode should change — a decision, not a passing fix. Also: `pyrightconfig.json` does not include `sdsc_submission_scripts` and excludes `tests`, so code in those trees is invisible to the blocking check. |

---

## 13. Expected artifacts

The manifest mode field and its consistency check; the `ScientificAuthority`
verdict with its tests and mutation proofs; the structured
all-trials-invalid feedback block; and a bounded real run that deliberately
collapses and proves non-authority.

---

## 14. Operator decisions — RESOLVED 2026-08-04

All three open questions are closed. The resolutions are binding and are
already reflected in §4 and §7.

| # | Question | Resolution |
|---|---|---|
| 1 | Default mode for a formal campaign | **No default.** A new formal campaign must declare both fields explicitly. Omission is refused before any LLM or GPU work. Policy is never inferred from a config filename. Historical manifests stay readable. |
| 2 | Does `diagnostic` differ behaviourally from `observe_only`? | **The question was the symptom.** They are different axes, not values of one (D-D-5): `healthgate_mode` ∈ {blocking, observe_only} governs control flow; `result_authority` ∈ {scientific, diagnostic} governs eligibility. `observe_only + scientific` is refused; `blocking + diagnostic` is now expressible and legitimate. |
| 3 | Retroactive labelling of V19 | **Do not rewrite.** V19 artifacts are immutable forensic evidence. A separate closure annotation records the classification, its basis and its retrospective date, with before/after hashes proving nothing was touched (§4.5, commit 10). |

| 4 | Is a **mixed** effective config a refusal? | **No — the question was posed at the wrong level (operator, 2026-08-04).** Mixed *roles* are the correct and normal configuration; mixed *semantics within one role* are the defect. See §4.6. |
| 5 | Must the exclusion count reach the **LLM-facing** interpretation input? | **Default: no (operator, 2026-08-04).** The exclusion must reach the final report, but deterministically. See §4.7. |

### Still open

Nothing blocks the commit plan. Both implementation-time questions that
stood here were **answered by the §15 re-audit**:

| # | Question | Answer (re-audit, 2026-08-05) |
|---|---|---|
| A | Does a deterministic report layer exist outside the interpretation agent (§4.7)? | **No.** `execute_tools/` contains no report-assembly module; the only "report"-shaped code is `core/runtime_control/gpu_measurement_*` and `scripts/official_paper_health_scan.py`, neither of which assembles campaign results. Commit 7 must therefore *create* the deterministic exclusion surface rather than filter an existing one. Recorded in §15.D. |
| B | Are `configured_action` / `effective_action` already derivable from the existing gate-result structure (§7 commit 9)? | **Partly.** `PersistedHealthGateResult` (`execute_tools/health_checks/schemas.py:300`) carries `resolved_action` and `would_invalidate_under_production_policy`, so the *effective* action and the production-policy verdict are both persisted today. The *configured* action is not persisted — it is re-read from the gate config at evaluation time (`evaluation.py:214-215`). Commit 9 adds only the missing half. |

---

## 15. Post-PR-E re-audit — read-only, 2026-08-05

Commissioned before implementation, against master `334d388d` (PR E merged
at `02f2709f`, master CI green). Every claim below was verified against
current code, and the load-bearing ones by execution.

### 15.A PR E impact: none

PR E added five new files under `core/` and `scripts/` and modified
`scripts/campaign_spend.py` (a predecessor hotfix). It changed **no**
launcher argument assembly, manifest, campaign stamp, HealthGate path,
tuner CLI, report path, historical-layout compatibility, or test harness
this PR reuses. The only overlap in the whole diff is a link line in this
document. Verified by file list, not inferred from PR scope.

### 15.B The central premise, confirmed by execution

`required_blocking_gate_ids` derives the scientific gate set from the
**enforcement action** (`candidate_eligibility.py:37-47`), not from a
declared role. Executed against both shipped configs:

```text
configs/health_checks.yaml                       -> ['amplitude_collapse_blocking',
                                                     'output_diversity_blocking',
                                                     'output_std_blocking']
configs/health_checks_baseline_observe_mode.yaml -> EMPTY SET
```

The two configs declare **identical gate id sets** and differ only in
action (9 `continue` + 3 `invalidate_round` versus 12 `continue`). So under
an observe-only config the scientific gate set silently collapses to
nothing, and `classify_candidate_health`'s `required.issubset(results)`
becomes trivially true. **This is exactly why `gate_role` must be a
declared typed property and can never be inferred from the action** — the
inference does not merely lose information, it inverts the answer.

### 15.C THE BLOCKER — two authority sources already disagree

**Found during the re-audit; not previously recorded; reproduced.**

| path | authority source | site |
|---|---|---|
| in-run trial selection | the **repo-current** shipped blocking config | `_best_trial_winner` → `is_valid_candidate(r)` with no `required_gate_ids` → `required_blocking_gate_ids()` with no path |
| resume-time incumbent | the **effective** config pinned by sha | `core/resume.py:378-392`, whose docstring states the repo-current config is *deliberately never used here* |

One record from an observe-only run — gate ran, check failed,
`would_invalidate_under_production_policy: true`:

```text
in-run  (_best_trial_winner path) : invalid
resume  (effective observe cfg)   : valid    required = EMPTY
```

**A record rejected during the run can become the incumbent on resume.**
This is a live correctness defect independent of PR D, and D-C4/D-C5
attach scientific authority to the path that currently answers `valid`.

**CLOSED by a predecessor hotfix, 2026-08-05** — branch
`fix/healthgate-scientific-role-consistency`. The operator chose a narrow
hotfix over pulling D-C1 forward, because any resume before PR D merges is
still exposed to the window. What landed:

- typed `gate_role` (`blocking` | `observational`) on `GateConfig`;
- identical roles declared in **both** shipped configs — three collapse
  detectors `blocking`, three recording metrics `observational` — so the
  two differ only in `on_fail`;
- one shared `resolve_scientific_gate_ids`, consumed by **both** the
  in-run and the resume-time path;
- historical role-less configs recovered through an audited compatibility
  map keyed on the exact pre-hotfix body sha (`3b552118…` blocking,
  `d133a12d…` observe-only), never inferred from the `_blocking` suffix,
  the action or the filename;
- an unaudited role-less config resolves to `None` → UNKNOWN → excluded.

`required_blocking_gate_ids` survives as a deprecated shim that collapses
UNKNOWN to the empty set; new code calls the resolver, which can express
UNKNOWN. The hotfix carries **only** role consistency — `healthgate_mode`,
`result_authority`, `ScientificAuthority`, zero-valid-trial authority,
deterministic reporting, planner feedback and the V19 sidecar all remain
PR D's work.

**The ruling it implements.** The **effective config remains
authoritative** — it is reproducible and resists repo drift, which is why
§3.3 chose it. The divergence is closed by making the scientific set come
from the **declared `gate_role`** rather than from the action, so an
observe-only run is non-authoritative *by declaration* instead of by an
empty gate set. This is folded into **D-C1** (declare the role) and
**D-C3** (derive authority from it), not a separate commit.

Consequence for the commit plan, **as amended once the hotfix landed**:
the role schema, both config declarations and the shared resolver are
already on master, so **D-C1 does not repeat them**. D-C1 returns to its
original scope (campaign mode/authority declaration and recording), and
D-C3's `from_context` consumes the role-aware **formal validity** the
shared resolver produces rather than a raw `gate_role` input. D-C7b must
no longer describe the gate entry model as "gaining a role" — it has one.

**A second defect the hotfix exposed**, worth carrying into PR D's test
standards: `test_repo_policy_never_consulted` was **vacuous**. It
monkeypatched the resolver and asserted on its argument, but the fixture
never stamped a `health_config_sha256`, so `_commit_time_gate_ids`
returned on the missing-stamp branch and the guard was never reached. The
mutation that made resume read the repo-current config was **not caught**
until the test was rebuilt on a reachable scenario and made to assert that
its own guard fired.

### 15.D Deterministic reporting has no existing home

There is no report-assembly layer outside the interpretation agent
(question A above). Commit 7 creates the deterministic exclusion surface;
it does not filter an existing one. This does **not** make it LLM-facing —
§4.7's ruling stands — but it does mean commit 7 is larger than "add a
filter" and must state where the surface lives.

### 15.E Legacy claims reconciled

§12A previously implied both of:

```text
all legacy records without the new field are excluded
historical replay preserves the previous incumbent
```

These are jointly unsatisfiable.

> **SUPERSEDED — operator decision 2026-08-05.** The rule this section
> originally proposed —
> *"effective config recoverable by sha → reconstruct, classify normally"* —
> is **withdrawn**. It conflated two axes. Exact-SHA recovery reconstructs
> the **HealthGate mode and validity** facts; it cannot reconstruct
> `result_authority`, which no historical run ever persisted.
>
> **Measured, 249 real artifacts under `/home/klz/Data/SIDEREIS_DATA`**
> (audit recorded under D-C4): `healthgate_mode` absent in **249/249**,
> `result_authority` absent in **249/249**. `run_invariants_lock.json`
> records scope, `health_gate_enabled` and the config sha — no authority.
> Of the 42 artifacts stamping a config sha, all 42 have a recoverable
> effective config, and resolving those 4 distinct configs yields a
> determinable mode (1 blocking, 3 observe-only) — **and still no
> authority**.
>
> Since `authoritative` requires `scientific`, and `scientific` is
> recoverable from nothing, **no historical record can reconstruct to
> authoritative.** Inferring it from a blocking configuration would invent
> a declaration nobody made — precisely what D-C1b refuses at launch.
>
> **The rule that governs is therefore:**
>
> ```text
> missing the new authority contract
>   -> remains readable, remains unchanged
>   -> scientific authority NOT established
>   -> never the new-authority incumbent
>   -> never in new-authority scientific aggregation
> ```
>
> No finer classification — observe-only versus blocking, reconstructable
> versus not — is required or wanted. "Preserves the previous incumbent"
> is **not** a property PR D delivers on the authority axis, and this
> document no longer claims it.

### 15.F Verdict

**Ready for implementation once D-C1/D-C3 carry the 15.C ruling.** No stop
condition in §11 was triggered: no historical artifact needs rewriting, no
scientific threshold changes, and GPU admission and O-7 are untouched.


---

## 17. Gate 1 — combined LLM-facing acceptance, 2026-08-05

**Decision, made autonomously**: ONE bounded run covering D-C5, D-C6 and
D-C7b together, deferred until all three were stable so the Gate proves
the FINAL prompt rather than an intermediate one. D-C5 is included because
filtering `per_model_formal` changes LLM-visible aggregate facts even
though §4.7 keeps the exclusion REPORT out of the prompt.

**Setup**: real OpenAI `gpt-5.4` proposer via `llm_configs/openai_tiered_v1.json`;
pseudo training (no GPU, no training loop). Two real calls total (initial
run + re-run after the defect below). ~60-67 s each, cost well inside the
standard's $0.05-0.20 estimate.

**Staged cheaply first**, per policy: structural tests → deterministic
renderer tests → real call. The first three stages are permanent unit
tests, not Gate-only scaffolding.

| property | result |
|---|---|
| P1 the trial-validity block renders when populated | PASS |
| P1b it reaches the prompt on the path that ACTUALLY ran | PASS *(after the fix)* |
| P2 the real LLM returns schema-valid output given it | PASS — `skip_bottleneck_mixer`, expert advice present |
| P3 no task-specific content in the generic template | PASS — zero leaks |
| P5 healthy run suppresses the block entirely | PASS |
| P5b legacy path suppresses it too | PASS |

**GATE 1 FOUND A REAL DEFECT, which is the point of running it.** The
first run passed every property except the one that mattered: the proposer
took the **legacy** branch (`Proposed model (legacy)`), while the wiring
had reached only the **pipeline** template. The block never entered the
prompt the model actually saw. No unit test caught it, because each tested
its own path.

This is the **mirror image** of the P3-V1 defect already recorded in the
proposal agent, where a legacy-only splice never reached pipeline mode.
Both directions have now occurred. Fixed by splicing into
`_build_reasoning_prompt` as well, adding the block to the token
accounting, and adding `TestBothPromptPathsCarryTheBlock` so a future
one-path wiring fails in unit tests rather than at a Gate.

Re-run on the fixed code: **PASS**, with P1b and P5b added so the Gate now
asserts the executed path rather than assuming it.

**Consequence recorded**: `_audit_proposer_components`' expected key set
grew by one. That test pins the exact set precisely so a new prompt
component cannot escape token accounting — it failed correctly and was
extended, not weakened.


---

## 16. Formal-gate policy — FROZEN, 2026-08-05

Two read-only audits established the current behaviour and the original
intent; the operator's ruling below closes the remaining question. This
section supersedes any earlier statement in this document that conflicts
with it.

### 16.A What `force_formal_round` actually is

**Not an operator override.** It defaults to `True` and forces
`plan.is_trial = False` on the last round of every iteration regardless of
what the planner picked — the "cross-architecture comparable formal score"
contract the interpreter and proposer depend on
(`agent/schemas/hyperparam_tuning.py:1188-1206`). Setting it `False` is
documented as *"ONLY for testing/debugging"*.

Every earlier passage in this document describing a formal round as
"explicitly overridden" was reasoning from the name. Formal on the final
round is the **default**, so the skip gate is the only thing that can
prevent it.

### 16.B The measured launch behaviour

Executed through the real helpers, production posture (switch ON,
skip Δ 0.0, bypass Δ 0.5, incumbent 10.0):

| trial evidence | winner | skip | bypass | formal |
|---|---|---|---|---|
| no records | none | False | False | **RUNS** |
| all invalid (99.0, 50.0) | none | False | False | **RUNS** |
| invalid 99.0 only | none | False | False | **RUNS** |
| valid 9.0 | 9.0 | **True** | False | skipped |
| valid 10.0 (`== skip`) | 10.0 | False | False | RUNS |
| valid 10.5 (`== bypass`) | 10.5 | False | **True** | RUNS, budget bypassed |
| **no incumbent**, valid 0.001 | 0.001 | False | False | **RUNS** — gates inert |
| **no incumbent**, valid 99.0, budget infeasible | 99.0 | False | False | **SKIPPED** — bypass could not fire |

The last row is the v15 failure `8f1cf528` was written to fix, reappearing
because the reference is absent rather than because the gate is wrong.

### 16.C The bootstrap reference — OPERATOR DECISION

**When the chain has no restored HealthGate-valid formal incumbent, the
effective comparison reference is `-inf`.**

Consequences, accepted deliberately: the first HealthGate-valid trial is
never skipped, always clears any finite bypass threshold, bypasses the
formal time budget, and establishes the chain's first formal baseline.
From the next iteration the restored incumbent takes over and the gates
tighten as the chain improves — the behaviour `8f1cf528` described.

**No task-owned bootstrap artifact.** An earlier audit recommended seeding
from a configured baseline; that recommendation is **withdrawn**. The
historical seed was `5.5763`, and the repository classifies it in three
independent places as the **class-127 phantom** — a *collapsed* model
scoring well by a PSD artifact
(`scripts/official_paper_health_scan.py:5`;
`paper_and_collapse_reference_baselines.md:21` classifies the paper-spec
wavenet baseline as **"Trained-but-collapsed"**, `mode_fraction ≥ 99.4%`,
which fails all three role-`blocking` gates). Seeding it would give a
collapse artifact gate authority over every new chain, and
`test_delta_gates.py:250` already forbids phantom defaults. Every
documented paper baseline is collapsed, so **there is no valid artifact to
bootstrap from** — which is why `-inf` is the answer rather than a lookup.

**Representation — `-inf` is a resolver value, never a stored one.**

```text
current_run_best_formal_score is not None
  -> effective reference = that value
  -> source = restored_valid_formal_incumbent

current_run_best_formal_score is None
  -> effective reference = float("-inf")
  -> source = negative_infinity_bootstrap
```

The persisted form stays `None`; provenance records the source:

```json
{"formal_comparison_reference": null,
 "formal_comparison_reference_source": "negative_infinity_bootstrap"}
```

Non-standard JSON `Infinity` is not emitted. `29ec0542` removed a fixed
`0.0` default precisely because a stored sentinel became a silent policy;
`-inf` must not repeat that as a stored value.

*Audited, not assumed*: `current_run_best_formal_score` is **not** an
operator-facing CLI flag. Its only supply path is
`resume state → run_one_iteration.py:1687 → workflows/model_exploration.py:1471,1885 → tuner input`.
No new CLI surface is required.

### 16.D Launch validity and result authority are separate

**Launch** asks: is there evidence worth spending a formal round on?

```text
winner = _best_trial_winner(memory_history)     # the single source
winner is None                       -> skip formal
winner.score <  ref + skip Δ         -> skip formal
winner.score >= ref + bypass Δ       -> bypass the formal time budget
otherwise                            -> ordinary time-budget decision
```

**Authority** asks: once a formal result exists, may it inform science?

```text
the formal record itself passes role-aware HealthGate validity
AND result_authority == scientific
AND (for historical records) authority is reconstructable
```

`valid_trial_count` and `no_valid_trial` are **removed as
formal-authority blockers**. A first formal result that bypassed on the
`-inf` bootstrap is no less authoritative for it; authority is a property
of the result, not of how the launch was justified.

`result_authority=diagnostic` does **not** suppress or bypass launch
gates. A diagnostic run still obeys skip / budget / bypass; its results
simply never become scientific. Any future "run formal with no valid
trial" need is a **new explicit launch override**, never a reuse of
`force_formal_round`.

### 16.E The delta-ordering invariant

```text
skip_formal_min_delta <= bypass_formal_time_budget_min_delta
```

Measured: inverting them makes **both** gates fire
(`skip Δ 1.0, bypass Δ 0.0` → thresholds 11.0 / 10.0 → scores 10.0-10.9
return `skip=True` and `bypass=True`), and the schema accepts it with no
validator. Today skip is evaluated first and short-circuits, so precedence
is **statement order, not policy**. An inverted ordering is a
**configuration refusal**, not a precedence rule.

### 16.F Single source for the trial best

`_best_trial_winner(memory_history)` stays authoritative for the current
iteration's best HealthGate-valid trial. It is recomputed deterministically
from records, already filters on validity, and already returns the **whole
record** — which formal plan inheritance needs and a score-only field could
not supply. `best_valid_trial_denoising_score` remains persisted
provenance and must not become a second authority.

**No mutable `best_valid_trial_score` is introduced.** A running value
would add an update-ordering question and a resume-restoration question
that the deterministic recomputation does not have.

### 16.G Ownership

| checkpoint | owns |
|---|---|
| **D-C1b** | delta-ordering refusal (16.E) |
| **D-C3** | no-winner ⇒ skip; effective-reference resolution + provenance (16.C) |
| **D-C2a/b** | authority derived from the formal record; `valid_trial_count` removed (16.D) |
| **D-C8/doc** | purge remaining "explicitly overridden formal" language (16.A) |

### 16.H Validation impact

Layer 1 gains the 16.E refusal and the 16.C source resolution. Layer 2
gains the 16.B matrix as scenarios, including both no-incumbent rows.
Layer 3's scenario changes from *"zero valid trials + explicit override →
formal runs non-authoritatively"* to **"zero valid trials → formal is
skipped"**, plus a first-valid-trial run proving the `-inf` bootstrap
bypasses the budget and establishes the first baseline.
