# Operating a run

**Audience**: whoever is watching the GPU.
**Answers**: what a run is doing, how to steer it, and what its refusals mean.

---

## What one iteration does

```
interpret        read every record so far; say what the evidence supports
  ↓
literature review (optional)   surface recent papers as soft priors
  ↓
propose          an architecture + an explicit prediction about its behaviour
  ↓
implement        write the model plugin (and optionally a loss plugin)
  ↓
validate         load it, run its tests, check the contract, gradient flow, LLM review
  ↓
tune             N rounds, each: plan → train → infer → score → health → reflect
```

The tuner is where compute is spent. Each round the planner proposes
hyperparameters, the model trains, inference produces deliverables, the metric
scores them, health gates judge validity, and the reflector interprets the round.

**Trial versus formal.** Trial rounds are cheap explorations under a reduced
budget. A trial that looks promising is promoted to a formal round, which is what
produces a competing candidate. Delta gates suppress spurious promotions when a
new plan barely moves the score.

## Steering a run

| you want to | do |
|---|---|
| see what would happen, spend nothing | `--dry-run` |
| bound the work | `--num_iterations`, `--max_rounds`, `--max_proposal_attempts` |
| bound the wall time | `--trial_time_budget_minutes`, `--formal_time_budget_minutes` |
| bound memory | `--trial_vram_budget_gb`, `--formal_vram_budget_gb` |
| use only some of the data | `--data_scope 4-9` (+ in-scope `--health_gate_files`) |
| stop health gates blocking | `--healthgate_mode observe_only` |
| turn the health subsystem off | `--no-health_gate_enabled` |
| inject human guidance | `--human_advice_file` |

Time budgets matter more than they look. Without them, a badly chosen data
portion from the planner can produce multi-hour rounds.

## Resume

Auto-resume is **on by default**. Re-running the same command against the same
workspace continues from the first incomplete iteration; if all iterations are
complete it exits cleanly rather than redoing work.

```bash
--no_auto_resume     # force a fresh start regardless of workspace state
--start_iter N       # pin manually, overriding the inspector
```

## The invariants lock

At startup a run writes `{workspace}/run_invariants_lock.json`, pinning:

- the resolved data scope,
- whether health gates are enabled,
- the sha256 of the effective health configuration.

Resuming, seeding from, or reusing that workspace with any of these different
**fails at startup**. This is deliberate: aggregate scores are only comparable
within one scope and one health configuration. A workspace that silently accepted
a change would be producing numbers incomparable with its own history — and
nothing downstream would know.

If you need different settings, use a new workspace.

## Reading what happened

Every node writes its output record to
`{storage.local.workspace}/{node}_{run_name}.json`. These are **logs, not
channels** — nodes never read each other's files; data flows through typed
protocols in memory. Read them to understand a run, not to wire anything.

Records carry provenance: the composition fingerprint, the effective health
config hash, the resolved scope, and — for file-declared plugins — content
hashes. Two records with the same fingerprint were produced under the same
declared semantics.

The dashboard (`python dashboard/main.py`, then `http://localhost:8000`) browses
results interactively. For a remote run, tunnel it:
`ssh -L 8000:localhost:8000 <host>`.

## Failures and refusals

SIDERIUS distinguishes *failing* from *refusing*, and the distinction is worth
learning.

| outcome | meaning | what to do |
|---|---|---|
| **round invalidated** | a blocking health gate fired — the output was not valid enough to count | nothing; the loop already knows |
| **`not_scoreable`** | the metric's scoreability contract refused before arithmetic | check the deliverable was written and is readable |
| **validation failure** | the generated model failed a validator check | the loop retries with error feedback, up to `--max_proposal_attempts` |
| **over-budget proposal** | the proposer's VRAM or wall-time estimate exceeded the budget | the loop asks for a revision, up to 3 rounds |
| **composition refused** | a manifest problem | see [define a task](define-a-task.md#when-it-refuses) |
| **startup lock mismatch** | this workspace was created under different invariants | use a new workspace |
| **exit code 2** | a formal launch without `--healthgate_mode` / `--result_authority` | supply both — they have no defaults on purpose |

A run that stops early on a streak of failed rounds is doing so by design
(`--max_fail_rounds`), not crashing.

## Cost control

- The planner and reflector can use different models
  (`--reflect_provider` / `--reflect_model_id`) — roughly halves top-tier quota
  use.
- `llm_configs/*.json` route each stage to a chosen provider and model.
- Trial rounds exist precisely so that formal-budget compute is spent on
  candidates that have already shown something.

## Health gates during a run

Gates fire at **tuner round boundaries**, not inside scoring. A blocking failure
resolves to one of `invalidate_round`, `skip_to_formal` or `skip_iter`; when
several fire, severity resolves
`skip_iter` > `skip_to_formal` > `invalidate_round` > `continue`.

Remember what a PASS means: nothing detectably invalid. Not "good". See
[health gates](../concepts/health-gates.md).

---

## Next

- [Entrypoints and CLI](../reference/entrypoints.md)
- [Configuration map](../reference/configuration-map.md)
- [Health gates](../concepts/health-gates.md)
