# PR 04b — Task description single source — detailed design (child)

Parent: [`../step_04_candidate_creation_mechanics.md`](../step_04_candidate_creation_mechanics.md)

| Field | Value |
|---|---|
| Design base | `e802b810` |
| Depends on | the **§13 task-profile authority**. **Independent of 04a** |
| Status | **DESIGN — awaiting operator review. NOT frozen.** |

---

## 1. Capability / final effect

> The task description has exactly **one** source. The lit-review node
> and the **static builtin model-description task content** read that
> source instead of a byte-duplicated copy, so changing the task means
> editing one file.

Today it means editing two, and nothing detects divergence.

## 2. Source evidence

`configs/task_config.yaml:10` and `configs/lit_review_config.yaml:48`
each declare a `task_description:` block. Audited at `e802b810`, they
are **byte-identical**:

```text
full-spectrum 1-D time-series denoising of SQUID dark-matter
detector data: map a noisy [B, T] integer signal to a clean
[B, 256, T] reconstruction, trained across the whole frequency
spectrum at once (not split into per-band models).
```

`lit_review_config.yaml:44-47` documents a further fallback to a default
constant in `agent/prompt_templates/literature_review/__init__.py`, with
a load-time warning. So one task fact currently has **up to three**
sources. Roadmap §13.1 names this precisely: *"duplicate byte-equal task
description in lit_review_config.yaml (TWO files to edit one task) +
stale SIDERIUS_TASK fallback prose"*.

## 3. Scope

1. Collapse the duplicate: `lit_review_config.yaml` stops declaring
   `task_description` and resolves it from the single task profile.
2. Resolve the fallback-constant precedence explicitly and fail
   visibly rather than silently rendering stale prose.
3. **Static builtin model-description task content** — the checked-in
   `ml_models/{model_type}/description.md` files. Enumerated at design
   time: **6 files** (`wavenet`, `punet`, `rnn`, `transformer`,
   `fcnet`, `gated_fno`), of which **2 carry SQUID/axion task prose**
   (`punet`, `gated_fno`). Those two get a task-block seam **only if a
   live consumer exists in this PR**; a seam without a consumer is
   deferred, not invented.

   **This is NOT the implementor-generated candidate description
   artifact** (`agent_generated/models/{model_name}/description.md`,
   written by `ml_model_implementor.py:1776-1796`) — that surface is
   **04a's**. `ml_models/model_descriptions.py` is the shared *loader*
   and is changed by **neither** PR. Different files, different
   producers: this is why the two-PR split is independent (parent
   §2.3.1).

### Non-goals

- No change to lit-review *format* doctrine, search strategy, or paper
  corpus — those are module-owned, not task-owned.
- No new prompt-assembly layer; extend the existing single-template +
  placeholder mechanism (roadmap §13.2).
- No planner/reflector/interpretation prose (Steps 07a/09).
- Nothing from 04a.

## 4. First production consumer

The production lit-review node, which renders `task_description` into
its search/extract/synthesis prompts.

## 5. Stage-A parity

| Surface | Criterion |
|---|---|
| `pb9_*` lit-review goldens (10) | **EXACT byte equality** |
| kwargs reaching `LLMBridge` | unchanged |

Because the two sources are byte-identical today, collapsing them must
be a **provable no-op** on rendered output. If any `pb9_*` byte moves,
that is a defect in the collapse — not a golden to update.

## 6. Stage-B atomic rung

| Rung | Varies ONLY | Reds when |
|---|---|---|
| **13.4-A (lit-review half)** | the task-description text | the lit-review node still renders the old text from its own config — i.e. the duplicate is still authoritative |

Step 01 landed 13.4-A for the proposer group; this is the remaining
lit-review half. Residue assertions stay **scoped to the
description-derived block** (parent §6) — a whole-prompt absence
assertion is unsatisfiable and would be a test-design error.

## 7. Checkpoint C — live integration

In a real chain iteration, the production lit-review node renders from
the single source. Provable from the run's prompt/token artifacts.

## 8. Failure classes

1. Divergence returns silently — two sources drift again with nothing
   detecting it.
2. The fallback constant masks a missing profile value.
3. A rendered lit-review byte changes (would break `pb9_*` parity).
4. Format doctrine accidentally reclassified as task content.

A guard that fails when a second `task_description` source reappears is
the highest-value test here — it names a defect nothing else catches.

## 9. Test disposition

| Test | Verdict |
|---|---|
| `test_agent_card_task_config.py` | **UPGRADE** to the single source |
| `test_step00_prompt_goldens.py` (pb9) | **KEEP** — the parity oracle |
| pins asserting `lit_review_config.yaml` carries its own description | **REWRITE** — they defend the duplicate |

## 10. Gates

| Gate | Decision |
|---|---|
| **Gate 1** | **NOT REQUIRED** — config single-sourcing with byte-identical rendered output ("Config files, YAML, schema-only → Unit only"). **Flip**: if any rendered lit-review byte changes, Gate 1 becomes REQUIRED |
| **Gate 2** | **NOT REQUIRED** — no execution-path change. **Flip**: if the collapse touches any node's execution path |

## 11. Validation budget

The `pb9_*` goldens, the 13.4-A rung, the duplicate-source guard, and
exact-head CI. Deliberately small — this PR's risk is concentrated in
one property (rendered bytes unchanged) that an existing oracle already
measures.

## 12. Rollback boundary

Two config files, the lit-review resolution path, their tests.
Independent of 04a.

## 13. Stop conditions

- The fallback-constant precedence turns out to encode a real operator
  behaviour rather than stale prose → surface it, do not silently
  delete.
- The static builtin model-description task content has no live
  consumer → defer it rather than create consumer-less seams.
- Any need to touch `ml_model_implementor.py`'s generated description
  path, or `ml_models/model_descriptions.py` → **STOP**: that would
  break the independence this split rests on (parent §2.3.1).
- Any `pb9_*` byte change that cannot be shown to be a defect in the
  collapse → STOP and surface as an operator decision.

## 13.1 Operator decisions

`OD-S4-2` (TWO PRs, `04a → 04b`) is **APPROVED**, with independence
re-verified against source after the description-surface clarification.
`OD-S4-1`, `OD-S4-3` and `OD-S4-4` do not touch this PR (no `pb5_*`
golden, no plugin corpus, no convergence surface here).

**Remaining operator questions for 04b: NONE.**

## 14. Implementation ledger

*(empty — populated at implementation kickoff)*
