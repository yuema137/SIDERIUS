"""What the ``train_time_s`` / ``validation_time_s`` split means — ONE authority.

F-SCANE-3 lifted the validation term onto the record so an LLM could finally
see the number it is asked to attribute. It then stated what the term means in
**four** places — two LLM-facing renderers and two Pydantic field descriptions
— and all four said the same two things, both of them false:

1. *"Validation time ... does not shrink when the model shrinks."*
   ``train_engine_sandbox._validation_pass`` runs ``output_seq =
   model(input_seq)`` per batch. That is a forward pass of the model under
   test, so a smaller or cheaper model makes the pass cheaper.

   **The first correction of this module was itself false, and this is that
   repair (N-4b).** It replaced the claim above with *"a forward pass of the
   model under test over a FIXED evaluation scope, so it shrinks with a
   smaller model but not with fewer epochs or less training data."* Both of
   those clauses are wrong:

   * **The evaluation scope is not fixed in a trial round — it is the
     planner's own lever.** ``policy._resolve_sample_set_cfg``'s ``trial``
     branch returns ``"eval_portion": plan.eval_portion``; that value reaches
     ``scope_acquisition.build_eval_scope(portion=eval_portion)``, becomes the
     attempt's ``eval_sample_set``, crosses as ``--eval_sample_set_json`` and
     is materialized as the validation dataset. ``agent/prompts.py`` asks the
     model for ``eval_portion`` by name ("fraction of segments per file for
     **validation**") and tells it to *increase* it; on the campaign path the
     value is ``AGENT_CONTROLLED``. Only a FORMAL round fixes it (strategy
     locked to ``snapshot``, portion from the operator's
     ``formal_eval_portion``). An optional ``validation_max_samples`` ceiling
     (07c C6, default ``None``) caps the eval leg but does not make it fixed.
   * **It is paid once per epoch.** ``_validation_pass`` is called INSIDE the
     ``for ep in range(train_cfg.epochs)`` loop, appending ``validation_
     seconds`` and accumulating ``validation_seconds_total`` per epoch, and
     ``records._validation_time_s`` reports the SUM. Today the real path runs
     ``max_epochs=1``, so this clause names a lever with no range yet —
     D-BUD-6's frozen ``trial_max_epochs: 2`` gives it range the moment it
     lands. The trial-scope clause above carries the finding on its own.

   Why that mattered enough to be a release blocker: the planner reads this
   sentence immediately before *"the time budget is a HARD UPPER LIMIT ... if
   the last run exceeded it, reduce model complexity"*. Telling it that the
   one cost component it directly authors in trial rounds is fixed steers a
   large overrunning candidate toward capacity reduction instead of the cheap,
   agent-owned eval reduction — F-SCANE-3's own failure class ("the agent is
   told to attribute to architecture a cost it cannot see") reproduced by
   F-SCANE-3's remediation, one lever over.

   What validation genuinely does NOT respond to is the training-scope levers:
   ``trial_portion`` and ``train_portion`` size the TRAINING scope only.

2. *"the architecture's own cost is ``train_time_s - validation_time_s``".*
   ``train_time_s`` is the PARENT's wall clock around the whole training
   subprocess (``ml_hyperparameter_tune_agent/execution.py``), while the
   trainer's own architecture-cost analogue starts at ``t_train_start``,
   which is set AFTER setup completes. So the residual also carries process
   spawn, CUDA init, model/optimizer construction, epoch-0 dataset
   materialization and checkpoint save — fixed overhead that no design
   change removes. The residual is an UPPER BOUND on the architecture's
   training cost, never the cost itself.

Consequence of both together, under a hard time budget: the planner was told
to ignore the one term that DOES respond to shrinking the model, and to
attribute to its own design a residual that includes cost no design can
remove — systematically under-pricing large candidates and over-pricing small
ones.

**Why this module exists at all.** Four copies of a sentence are four chances
to drift, and the drift is invisible: each site reads correct in isolation.
The renderers, the coherence rule and the prose now live here, and every
surface that states the split imports it. A leaf module by construction — it
imports nothing from the project, so a schema module may consume it without a
cycle.
"""

from __future__ import annotations

#: The three facts, stated once. Consumed verbatim by the planner prompt and
#: by the two ``timing`` field descriptions, so a surface cannot disagree with
#: another surface about what its own numbers mean.
TIMING_SPLIT_SEMANTICS = (
    "`train_time_s` is the WHOLE training subprocess and INCLUDES the validation "
    "pass. `validation_time_s` is that pass, summed over epochs: once per epoch "
    "the model under test runs a forward pass over the round's EVALUATION scope. "
    "It therefore shrinks with a smaller model, with fewer epochs, and with a "
    "smaller `eval_portion` — in a trial round that is the plan's own value, so "
    "the evaluation scope is a lever you set, not a fixed cost (a formal round "
    "fixes it). What it does NOT respond to is `trial_portion` / `train_portion`: "
    "those size the TRAINING scope only. The remainder "
    "(`train_time_s - validation_time_s`) is NOT the architecture's own cost "
    "either — it still contains process start, CUDA init, model and dataset "
    "construction and checkpoint save — so treat it as an UPPER BOUND on what "
    "the architecture costs."
)

#: The same sentence, newline-terminated for insertion into a prompt block.
TIMING_ATTRIBUTION_NOTE = TIMING_SPLIT_SEMANTICS + "\n"

#: What the residual is called wherever it is rendered. Deliberately NOT
#: "architecture cost": naming it that is the claim this module exists to
#: retract, and a label is read far more often than a note.
REMAINDER_LABEL = "training+overhead"


def is_coherent_split(train_s: float, val_s: float | None) -> bool:
    """Whether the pair can be believed well enough to render a split.

    A part cannot be negative, and cannot exceed its whole. Production cannot
    produce either (the validation pass runs inside the timed subprocess), so
    a violation means the two numbers came from different clocks — a
    pseudo/stub record, a hand-edited artifact. Rendering a negative remainder
    at an LLM would be worse than rendering nothing.

    Args:
        train_s: the whole training subprocess wall clock, in seconds.
        val_s: the validation seconds folded inside it, or ``None`` when the
            producer recorded no split. ``None`` is an ABSENT split, never a
            zero one, and is not coherent to render.

    Returns:
        ``True`` only when a split may be stated.
    """
    return val_s is not None and 0 <= val_s <= train_s


def render_planner_train_term(train_s: float, val_s: float | None) -> str:
    """The planner block's ``train=...`` term, in minutes.

    Falls back to the un-split form — byte-identical to its pre-F-SCANE-3
    self — when the producer recorded no split or the split is incoherent.
    """
    if val_s is None or not is_coherent_split(train_s, val_s):
        return f"train={train_s / 60:.1f} min"
    return (
        f"train={train_s / 60:.1f} min "
        f"(validation {val_s / 60:.1f} min of that; "
        f"{REMAINDER_LABEL} {(train_s - val_s) / 60:.1f} min)"
    )


def render_discovery_train_term(train_s: float, val_s: float | None) -> str:
    """The timing discovery's ``train=...`` term, in minutes, unit-suffixed by
    its caller. Same fallback rule as the planner term."""
    if val_s is None or not is_coherent_split(train_s, val_s):
        return f"train={train_s / 60:.1f}"
    return (
        f"train={train_s / 60:.1f} incl. validation {val_s / 60:.1f}, "
        f"{REMAINDER_LABEL} {(train_s - val_s) / 60:.1f}"
    )
