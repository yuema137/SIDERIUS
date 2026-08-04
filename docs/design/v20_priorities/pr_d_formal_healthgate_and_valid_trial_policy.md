# PR D — Formal HealthGate mode and the zero-valid-trial policy

**Status: DESIGN — direction and all five deviations APPROVED by the
operator 2026-08-04; IMPLEMENTATION NOT YET AUTHORIZED.**

The three open questions are closed (§14). Two new ones (Q4 mixed config,
Q5 LLM-facing exclusion count) are recorded and must be answered from code
inspection before the commits they affect.

Written against `master` at `dd8d66aa` (PR C2 merged, `40d17f69`). Per the
folder rule in `README.md`, no implementation begins until the operator has
reviewed and approved this document; §20.6 is scope-level and the audit
below has already changed the design in five places (D-D-1 through D-D-5).

Parent scope: `docs/design/v20_priorities.md` §20.6.
Governing genericization contract: `v20_priorities.md` §1.4 (§8 here).
Predecessors: PR B (`4472f15`), PR C1 (`781e3e8a`), PR C2 (`40d17f69`).

**Dependency**: one operator decision — the default HealthGate mode for a
formal campaign (§12A.4 of the parent). Everything else is independent.
PR D touches no GPU measurement, no admission path and no O-7 accounting.

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
decisions** (D-D-1, as refined by the operator 2026-08-04). Zero valid
trials does not *cause* a formal execution: formal runs only through an
explicit diagnostic or `force_formal_round` override. Whether it runs or
not, it cannot be granted scientific authority.

When it does run it is fully persisted, labelled `diagnostic`, excluded
from incumbent selection, excluded from scientific aggregation and grand
means, never reported as a formal scientific result, and the planner
receives structured `all_trials_invalid` feedback carrying the gate
evidence and reasons.

The condition itself is already computed (§3.4).

### 4.3 Authority is a typed verdict carrying ALL its reasons

**Corrected by the operator, 2026-08-04.** The draft's basis list —
`valid_trial_supported` / `no_valid_trial` / `non_blocking_mode` — was
missing the axis D-D-5 introduced: a run declared `result_authority:
diagnostic` is non-authoritative **even with valid trials and blocking
gates**. And the reasons are not mutually exclusive: a run can be
`observe_only` **and** declared `diagnostic` **and** have zero valid trials
at once. Recording only one and pushing the rest into free text loses the
distinction an operator most needs — *why* a result was refused.

Following the shape PR C settled on for `PrephaseDisposition` — a **typed
value with computed consequences**, never a bare boolean and never an
exception:

```text
ScientificAuthority
  authoritative: bool
  primary_basis: AuthorityBasis                 the highest-precedence reason
  reasons: tuple[AuthorityBasis, ...]           EVERY reason that applies
  enters_incumbent_selection: bool              computed; False whenever authoritative is False
  enters_scientific_aggregation: bool           computed; False whenever authoritative is False
  detail: str                                   human-readable, never load-bearing

AuthorityBasis
  valid_trial_supported
  declared_diagnostic        result_authority == diagnostic
  non_blocking_mode          healthgate_mode == observe_only
  no_valid_trial             zero HealthGate-valid trials
  gate_invalidated           the formal result failed its own validity requirements
```

**Precedence, fixed and tested** (the invalid combination is already
refused at startup, so it cannot reach here):

```text
declared_diagnostic   -> non-authoritative
non_blocking_mode     -> non-authoritative
no_valid_trial        -> non-authoritative
gate_invalidated      -> non-authoritative
otherwise             -> authoritative
```

`primary_basis` is the first that applies; `reasons` carries **all** of
them, so a diagnostic run that also had no valid trials reports both.

Authority is granted **only** for:

```text
healthgate_mode  == blocking
result_authority == scientific
valid trials     >= 1
the formal result itself meets the existing validity requirements
```

The consequences are **computed properties of the verdict**, not separate
flags each consumer must remember to check — PR C's O-7 boundary is the
precedent: six frozen consequences derived from one disposition, so a new
consumer cannot forget one.

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

```text
gate_role = blocking       on_fail MUST carry invalidation authority
gate_role = observational  on_fail MAY be continue / record-only
```

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

> **The round runs only if explicitly overridden. Whether it runs or not,
> its authority is refused.**

**Operator refinement, 2026-08-04**: permitting a diagnostic formal is *not*
the same as automatically running one. Zero valid trials never *causes* a
formal execution — that requires an explicit diagnostic or
`force_formal_round` override. The two decisions are independent, and only
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
| **D-C1** | `healthgate_mode` + `result_authority` typed and validated (D-D-5); manifest fields; **mandatory declaration, mode↔config consistency, and invalid-combination refusal** (D-D-2) | `[ ]` not started |
| **D-C2** | `ScientificAuthority` verdict: computed consequences, typed `reasons`, fixed precedence incl. `declared_diagnostic` (§4.3); wired to the existing `valid_trial_records` (§3.4) | `[ ]` not started |
| **D-C3** | An **explicitly overridden** zero-valid-trial formal round still completes, recorded non-authoritative (D-D-1) | `[ ]` not started |
| **D-C4** | Incumbent exclusion — extend `resume.py`'s predicate, do not replace it (§3.6) | `[ ]` not started |
| **D-C5** | Aggregation/report exclusion, stated **deterministically** — not via the LLM (§4.7) | `[ ]` not started |
| **D-C6** | Structured all-trials-invalid feedback, extending `_build_gate_exhaustion` (§3.8) | `[ ]` not started |
| **D-C7a** | Typed `gate_role` metadata — **prerequisite for D-C1b** (§4.6.1) | `[ ]` not started |
| **D-C7b** | Five recorded fields per gate; honest display label; **ids never rewritten** (D-D-3) | `[ ]` not started |
| **D-C9** | V19 retrospective closure annotation, archive untouched (§4.5) | `[ ]` not started |
| **D-C8** | Doc sync — **skill, node, agent, launcher, CLI and example `.md` in the same change** | `[ ]` not started |

Mapping to §20.6: D1→D-C1, D2→D-C2, D3→D-C3, D4→D-C4, D5→D-C5, D6→D-C6.
D-C7a/b and D-C8 are additions this audit forced; D-C9 was added by the
operator's V19-immutability decision. Note the ordering constraint: **D-C7a
precedes D-C1b**, because a consistency check without typed roles would
have passed V19's own config (§4.6.1).

---

## 7. Commit plan

Eleven commits. Each is independently revertible and states its own Behavior
Delta. The ordering rule is PR C's: **the typed boundary lands before
anything consumes it**, so no commit adds branching to a consumer that
cannot yet be told the truth.

Nothing below is `[x]`. A step becomes `[x]` only when it is implemented
**and** verified with recorded evidence — the test name and count that
proved it, written back into this document at the checkpoint.

| # | Commit | Behavior Delta |
|---|---|---|
| 1 | `D-C1a` mode declared and recorded | none |
| 2 | `D-C7a` typed `gate_role` metadata (**prerequisite**, §4.6.1) | none — declared, not yet enforced |
| 3 | `D-C1b` mode↔config consistency check | **mismatched declaration fails at startup** |
| 4 | `D-C2a` `ScientificAuthority` verdict, no call sites | none |
| 5 | `D-C2b` verdict wired at the tuner exit | records carry authority; nothing consumes it |
| 6 | `D-C3` explicitly overridden zero-valid-trial formal recorded non-authoritative | none — the override already ran it |
| 7 | `D-C4` incumbent exclusion | **non-authoritative results stop entering the incumbent** |
| 8 | `D-C5` aggregation/report exclusion, deterministic (§4.7) | **non-authoritative results leave scientific aggregation** |
| 9 | `D-C6` all-trials-invalid feedback | planner receives structured evidence |
| 10 | `D-C7b` five recorded fields; honest display label | none (labels only) |
| 11 | `D-C9` V19 closure annotation (schema in Git; sidecar is an evidence step, §7) | none — archive annotated, never modified |

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
- [ ] Independently reviewable: adds a field, changes no decision.
- [ ] No unrelated cleanup; no follow-up work folded in.
- [ ] Before committing: show diff summary, staged file list, test output, and any deviation from this plan.

---

### Commit 2 — `D-C7a`: typed `gate_role` metadata (prerequisite for the check)

**1. Goal.** Give the consistency check in commit 3 a reliable notion of
"declared blocking". Without it the check must either trust the misleading
`_blocking` suffix (§3.2) or infer the mode from behaviour — and an
inference-based check **would have passed V19's config**, because inferring
the mode from the behaviour makes every config self-consistent by
construction (§4.6.1).

It is *before* the check and separate from the presentation work (commit
10) because only the metadata is a prerequisite; the display label is not.

**2. Scope.** The gate entry model (`execute_tools/health_checks/config.py:82+`)
gains a typed `role`; both shipped configs declare it.

*Non-goals.* **No gate id is renamed** — ids are join keys in every archived
artifact. No display change; that is commit 10. No enforcement; that is
commit 3.

*Dependencies.* None.

**3. Implementation plan.**
- [ ] Read the gate entry model and `HealthChecksConfig` load path before choosing the field's shape.
- [ ] Add `role: Literal["blocking", "observational"]` with a default that preserves current behaviour for configs omitting it.
- [ ] Declare it on every gate in `configs/health_checks.yaml` and `configs/health_checks_baseline_observe_mode.yaml`.
- [ ] Verify whether adding the key changes `health_config_sha256` for the shipped configs; if it does, record the expected new values and confirm no invariant lock compares across the boundary.

**4. Validation plan.**
- *Unit*: a role-less config loads with behaviour identical to pre-commit; both shipped configs declare a role on every gate; an unknown role is rejected by Pydantic.
- *Integration*: the materialized `health_checks_effective.yaml` carries the roles.
- *Negative*: `role: nonsense` refused at load.
- *Backward-compatibility*: a historical effective config without roles still loads.
- *Real Gate*: none.

**5. Acceptance criteria.**
- [ ] `git diff` shows **zero** changes to any gate id string.
- [ ] In the observe-only config, all three `*_blocking`-named gates declare `role: observational` — the id and the role now disagree **in the data**, which is the fact commit 10 will surface in the label.
- [ ] A role-less config produces byte-identical gate behaviour.
- [ ] Any `health_config_sha256` change is recorded here with both values.

**6. Failure and edge cases.**
| case | behaviour |
|---|---|
| config omits `role` | **fall back safely** to the behaviour-preserving default |
| unknown role literal | **stop** at load |
| id says blocking, role says observational | **legal** — that is the point; the label is fixed in commit 10 |

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
- [ ] Independently reviewable and independently revertible — reverting restores commit 1's record-only behaviour.
- [ ] Before committing: show the refusal message verbatim.

---

### Commit 4 — `D-C2a`: the `ScientificAuthority` verdict, with no call sites

**1. Goal.** Introduce the typed verdict and its computed consequences as a
pure unit. It is separate from its wiring for the reason PR C learned the
hard way: a boundary that lands together with its consumers cannot be
proven to be *reached*, and a verdict computed but never consulted is
exactly the defect class this PR exists to end.

**2. Scope.** One new module under `core/` owning `ScientificAuthority`,
its `basis` literal, and the derived `enters_incumbent_selection` /
`enters_scientific_aggregation` **as computed properties, never settable
fields** — the shape `prephase_admission.PrephaseAdmissionOutcome` already
uses for O-7.

*Non-goals.* Zero call sites. Nothing imports it yet.

*Dependencies.* None (may land in parallel with 1–2).

**3. Implementation plan.**
- [ ] Read `core/runtime_control/prephase_admission.py` first and mirror its structure: frozen model, literal disposition, consequences as properties.
- [ ] Define `AuthorityBasis` covering `valid_trial_supported`, `declared_diagnostic`, `non_blocking_mode`, `no_valid_trial`, `gate_invalidated` (§4.3).
- [ ] Carry `reasons: tuple[AuthorityBasis, ...]` with **every** applicable reason, plus `primary_basis` as the highest-precedence one — a run can be `observe_only` AND `declared_diagnostic` AND have zero valid trials at once.
- [ ] Implement the fixed precedence of §4.3 and test it directly.
- [ ] Make both `enters_*` properties `False` whenever `authoritative` is `False` — no independent path to `True`.
- [ ] Write the module docstring in the house style: what defect it prevents, and why the consequences are derived rather than flagged.

**4. Validation plan.**
- *Unit*: every basis; `authoritative=False` ⇒ both consequences `False`; the consequences cannot be set directly; **`declared_diagnostic` is non-authoritative even with valid trials and blocking gates**; a multi-reason case reports all reasons and the correct `primary_basis`.
- *Negative*: unknown basis rejected.
- *Mutation*: making a consequence an independent field must fail a test.
- *Real Gate*: none.

**5. Acceptance criteria.**
- [ ] For every basis, the tuple `(authoritative, enters_incumbent_selection, enters_scientific_aggregation)` matches a table written in the test, hardcoded — never read back from the model.
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

**1. Goal.** Compute the verdict from data that already exists (§3.4) and
attach it to the record. Separate from commit 3 so that "the verdict is
reached in production" is a distinct, provable claim.

**2. Scope.** `ml_hyperparameter_tune_agent.py` around the existing exit
bookkeeping (`:5255-5336`), reusing `valid_trial_records` (`:5270-5273`);
the output schema; the manifest mirror in `run_one_iteration.py` beside the
existing `best_valid_trial_score`.

*Non-goals.* **No consumer changes.** Incumbent and reporting are untouched
— commits 6 and 7.

*Dependencies.* Commits 1 and 3.

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
- [ ] For a run with zero valid trials, the record carries `authoritative: false`, `basis: "no_valid_trial"`, and **the same `best_denoising_score` as before this commit** — the verdict annotates, it does not alter the score.
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

### Commit 6 — `D-C3`: an explicitly overridden zero-valid-trial formal round remains runnable, and is recorded non-authoritative

**1. Goal.** Land D-D-1 explicitly, in the direction the title now states.
Zero valid trials **never causes** a formal execution — that requires an
explicit diagnostic or `force_formal_round` override. What this commit
proves is that when such an override *has* fired, the round is **not
cancelled** and its result is **not certified**. Its own commit so the "we
did not break the resilience at `:1487-1489`" claim is reviewable in
isolation.

The title was previously "a non-blocking formal round runs", which invited
exactly the reading the operator rejected — that `observe_only` or zero
valid trials would themselves trigger a formal round. They do not.

**2. Scope.** Verification and recording around `force_formal_round`
(`:1455-1492`). *Non-goals — and this is the point of the commit*: the
no-winner fallback keeps preserving the planner's plan and keeps logging its
WARNING. Control flow is unchanged.

*Dependencies.* Commit 4.

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

**1. Goal.** The first commit that changes a decision. Isolated so it can be
reverted without touching reporting.

**2. Scope.** `core/resume.py` — **extend** the commit-time-validity
predicate for `chain_best_valid_formal_*` (`:200-215`), do not replace it.

*Non-goals.* The commit-time-validity rule and its "repo-current config is
NEVER consulted" guarantee (`:306-310`) must survive untouched.

*Dependencies.* Commit 4.

**3. Implementation plan.**
- [ ] Read `:196-320` fully before editing.
- [ ] Add `enters_incumbent_selection` as an **additional** conjunct.
- [ ] Handle records predating the field: **UNKNOWN ⇒ excluded**, matching the existing treatment of unestablishable commit-time validity.
- [ ] Extend `validity_basis` provenance so an exclusion is auditable.

**4. Validation plan.**
- *Unit*: zero-valid-trial formal excluded; valid one still selected; legacy record without the field excluded as UNKNOWN.
- *Integration*: a multi-iteration chain picks the same incumbent as before when all results are authoritative — **default parity**.
- *Negative*: no record ⇒ `None`, never a fabricated incumbent.
- *Backward-compatibility*: replaying an existing chain workspace yields the same incumbent unless a zero-valid-trial result was previously selected — and if it was, that difference is the fix, and must be recorded.
- *Real Gate*: none.

**5. Acceptance criteria.**
- [ ] On a fixture chain where iteration N had zero valid trials and the best score, the incumbent after this commit is iteration M ≠ N, and `chain_best_valid_formal_provenance` names the exclusion basis.
- [ ] On an all-authoritative fixture, the selected `exp_id` and score are **identical** to pre-commit.

**6. Failure and edge cases.**
| case | behaviour |
|---|---|
| every candidate excluded | incumbent `None` — legitimate, not an error |
| legacy records only | all UNKNOWN ⇒ `None`; **warn** so it is visible |
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

**1. Goal.** Non-authoritative results leave scientific aggregation, **and
the exclusion is visible**. Separate from commit 6 because it changes what a
human reads rather than what the chain decides.

**2. Scope.** `nodes/result_interpretation_agent/result_interpretation_agent.py`
summary consumption (`:911`, `:924`, `:961`, `:1272`) and the report path.

*Non-goals.* No change to the frozen TIDMAD score formula. No change to how
a score is computed — only to which scores are aggregated.

*Dependencies.* Commit 4.

**3. Implementation plan.**
- [ ] Read each of the four `inp.summaries` loops before editing; they are not obviously equivalent and may need different handling.
- [ ] Filter on `enters_scientific_aggregation`.
- [ ] Emit an explicit "N results excluded as non-authoritative, because …" line — a silently smaller sample is the failure mode being prevented.
- [ ] **Find the deterministic report layer first** (§4.7). The default is that aggregation code derives the count and reasons and the report renders a fixed provenance section — no model involvement.
- [ ] Only if a code audit proves the final report is produced wholly by the interpretation agent with no layer able to append deterministically, fall back to an LLM-facing input — and **stop for separate approval** before doing so.

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

**1. Goal.** Close D6 by extending the existing gate-exhaustion block rather
than opening a second feedback channel (§3.8).

**2. Scope.** `_build_gate_exhaustion` and its call site (`:5279-5290`), and
the feedback schema it populates.

*Non-goals.* No new feedback channel. No prompt-text change unless the
schema demands it — if it does, it is LLM-facing and split out.

*Dependencies.* Commit 4.

**3. Implementation plan.**
- [ ] Read `_build_gate_exhaustion` and its schema fully; confirm it is the right carrier before extending it.
- [ ] Add the all-trials-invalid evidence to the existing structure.
- [ ] Determine whether any prompt text changes; if yes, **stop and split**.

**4. Validation plan.**
- *Unit*: the block is populated when zero trials are valid, absent otherwise.
- *Integration / pseudo*: it reaches the next iteration's planner input.
- *Negative*: a run with valid trials is unchanged.
- *Backward-compatibility*: the existing gate-exhaustion trigger behaviour is unaltered.
- *Real Gate*: none.

**5. Acceptance criteria.**
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
- [ ] Any prompt change is excluded from this commit by construction.

---

### Commit 10 — `D-C7b`: five fields recorded per gate; the operator-facing label stops lying

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

### Commit 11 — `D-C9`: the V19 retrospective closure annotation

**1. Goal.** Record what V19 actually ran under, **without touching a single
V19 byte** (§4.5, operator decision 2026-08-04). Last because it is
historical bookkeeping, and separate because it writes to the incident
archive rather than to production code.

**2. Scope — and this commit is deliberately only half of the work.**

```text
repository commit    the annotation schema + its validator/generator
evidence step        running it beside the immutable V19 archive,
                     and recording the before/after hashes
```

The V19 forensic archive is not in the Git repository, so the sidecar's
*generation* is an acceptance-artifact operation, not a code commit
(operator, 2026-08-04). Only the schema and generator are committed here;
pretending the generation is an ordinary commit would misrepresent where
the evidence lives.

*Non-goals — and this is the whole point*: **no V19 manifest is modified.**
No field is back-filled. Nothing in the archive is deleted or moved.

*Dependencies.* Commit 1 (so the vocabulary the annotation uses exists).

**3. Implementation plan.**
- [ ] Locate the V19 artifacts and confirm which config each iteration actually loaded, from the recorded `health_checks_config` / `health_config_sha256` — not from memory.
- [ ] Verify the observe-only classification from the recorded evidence: `on_fail: continue` in the effective config, and `would_invalidate_under_production_policy: true` on the rounds.
- [ ] Write the annotation with: original config path + sha256; the verified classification; the date and basis (2026-08 retrospective); and hashes of the unchanged source artifacts.
- [ ] Record the source hashes **before and after** writing the annotation, and show they are identical.

**4. Validation plan.**
- *Unit*: the annotation schema round-trips; a missing source artifact is reported, never guessed.
- *Integration*: none required.
- *Negative*: an artifact whose recorded sha256 does not match its content is reported as **tampered**, and the annotation refuses to classify it.
- *Backward-compatibility*: every V19 file hash is byte-identical before and after.
- *Real Gate*: none.

**5. Acceptance criteria.**
- [ ] `sha256sum` of every V19 artifact is **identical** before and after the commit, and the transcript of both runs is recorded here.
- [ ] The annotation states the classification, its basis, and its retrospective date, and does not claim the fields existed at run time.
- [ ] No V19 file appears in `git diff --stat` as modified.

**6. Failure and edge cases.** Recorded sha256 mismatch → **stop**, classify
nothing, report tampering. Config path no longer resolvable → record
`unresolvable` with the recorded sha256, never a guess.

**7. Verification commands and evidence.**
```bash
# before and after, compared
find <v19_artifact_root> -type f -exec sha256sum {} + | sort > /tmp/v19_before.txt
```
- [ ] hashes identical: __   - [ ] annotation reviewed: __

**8. Commit boundary.**
- [ ] Touches the archive and its annotation only; no production code.
- [ ] Before committing: show that `git diff --stat` contains no V19 artifact.

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
authoritative. Reuse the V19 collapse signature rather than inventing one —
the artifacts exist and the reproduction is the point.

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

Nothing blocks the commit plan. Two implementation-time questions remain and
are answered by reading code, not by deciding policy:

| # | Question | Answered by |
|---|---|---|
| A | Does a deterministic report layer exist outside the interpretation agent (§4.7)? | Reading the report assembly before implementing commit 7. |
| B | Are `configured_action` / `effective_action` already derivable from the existing gate-result structure (§7 commit 9)? | Reading the gate-result model before implementing commit 9. |

