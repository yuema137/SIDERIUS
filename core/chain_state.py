"""``ChainState`` — the exploration chain's mutable cross-iteration state.

Step 09.5a finding A-1: ``run_workflow`` initialised eleven accumulators as bare
locals and mutated them across an 813-line loop, with nine of them seeded from
``restored_*`` parameters. Nothing typed the boundary between "an authority this
run established once" and "a value that evolves as iterations complete", so
Step 10's new carried state would have landed in the same undifferentiated
scope.

This carrier owns exactly the second thing:

    values that are restored (or cold-started), mutated as iterations
    complete, and carried forward.

It is deliberately NOT a general context object. It holds no configuration, no
services, no authorities and no per-iteration scratch — those are
``WorkflowLaunchConfig``, the bindings carrier, and ordinary locals
respectively. :class:`workflows.run_config.WorkflowLaunchConfig` and
``WorkflowRunBindings`` both refuse this class's field names at construction, so
the separation cannot quietly erode.

RELATIONSHIP TO ``RestoredState``
----------------------------------
:class:`core.resume.RestoredState` remains the *transport* value: produced once
by ``restore_prior_state`` from disk, read-only, and crossing the launcher
boundary. ``ChainState`` is the in-process carrier constructed from it. Two
types because they have two lifecycles — making ``ChainState`` itself the
restored value would push a workflow-lifecycle type into the launcher's resume
API, which is Step-10 territory.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from dataclasses import fields as dataclass_fields
from typing import TYPE_CHECKING, Any

from agent.schemas.interpretation import PredictionMemory

if TYPE_CHECKING:  # pragma: no cover - typing only
    from agent.schemas.health_feedback import CollapseFingerprintHistoryEntry


@dataclass
class ChainState:
    """Mutable state carried across the exploration loop's iterations.

    Every field is here because it satisfies one rule: it is initialised before
    the iteration loop and mutated inside it. A value that is recomputed each
    iteration is a local, not a member — promoting one would start the drift
    toward a god object.
    """

    # --- results and progress -------------------------------------------------

    #: Every completed iteration's tuner output, in order. The workflow's return
    #: value.
    iteration_results: list[Any] = field(default_factory=list)

    #: Model types seen this run, seeded from the loaded tuning outputs and
    #: appended as new candidates are proposed.
    all_model_types: list[str] = field(default_factory=list)

    #: This EXECUTION's best raw formal score — print banner and workflow
    #: summary ONLY. Deliberately never seeded from restored chain state and
    #: never fed to the tuner (V19 PR 1 two-state design). Kept separate from
    #: :attr:`chain_formal_incumbent_reference` on purpose: they look alike and
    #: mean different things, and unifying them would silently change which
    #: number reaches a decision.
    best_score_overall: float | None = None

    #: The chain's formal-incumbent DECISION state. Seeded from
    #: ``RestoredState``; updated after each in-process iteration commit from
    #: that iteration's committed VALID formal, so an in-process multi-iteration
    #: run is equivalent to N chained subprocesses. Consumed only by the tune
    #: protocol.
    chain_formal_incumbent_reference: float | None = None

    # --- cross-iteration memory ----------------------------------------------

    #: The latest committed iteration's proposal, so the candidate channel
    #: survives the subprocess boundary.
    previous_proposal_data: dict | None = None

    #: The run's vocabulary. Restored value beats the static seed — without that
    #: priority every chain iteration resets to the seed
    #: (docs/Consistent_growing_vocab_list.md §1.2).
    current_runtime_vocab: list[Any] = field(default_factory=list)

    #: Typed collapse-fingerprint history. One direction: the restored value
    #: seeds this, and each iteration's interpreter output REPLACES it — the
    #: interpreter is the only merge point.
    current_collapse_fingerprint_history: dict[str, list[CollapseFingerprintHistoryEntry]] = field(
        default_factory=dict
    )

    #: Interpreter prediction memory. Same one-direction shape as the
    #: fingerprint history (Step 09a C5).
    current_prediction_memory: PredictionMemory = field(default_factory=PredictionMemory)

    #: Per-model Phase 1 cache, so the interpreter's cache-hit branch is
    #: reachable across the subprocess boundary. Mutated in place at iteration
    #: end, which is why :meth:`from_restored` copies defensively.
    model_knowledge_cache: dict = field(default_factory=dict)

    #: The most recent tune's ``ModelRunSummary``.
    latest_new_summary: Any = None

    #: Bounded FIFO of the last three tuner outputs, so the interp->propose
    #: protocol can surface their gate-exhaustion summaries to the next
    #: proposer. Bounded at construction, never by the mutation site.
    recent_tune_outputs: deque = field(default_factory=lambda: deque(maxlen=3))

    # --- construction ---------------------------------------------------------

    @classmethod
    def cold_start(cls, *, vocab_seed: list[Any] | None = None) -> ChainState:
        """First iteration, or an in-process run with nothing restored.

        This is the ONE place cold-start defaults are expressed;
        :meth:`from_restored` delegates to it for every value the restored state
        does not supply, so there is no second default expression to drift.
        """
        return cls(current_runtime_vocab=list(vocab_seed or []))

    @classmethod
    def from_restored(
        cls,
        *,
        vocab_seed: list[Any] | None = None,
        restored_runtime_vocab: list[Any] | None = None,
        restored_model_knowledge_cache: dict | None = None,
        restored_previous_proposal: dict | None = None,
        restored_chain_incumbent_score: float | None = None,
        restored_collapse_fingerprint_history: dict | None = None,
        restored_prediction_memory: PredictionMemory | None = None,
        all_model_types: list[str] | None = None,
        recent_tune_outputs: deque | None = None,
    ) -> ChainState:
        """Chain mode: seed from what the launcher restored.

        Each rule below is the one ``run_workflow`` already applied; they are
        collected here rather than changed.
        """
        state = cls.cold_start(vocab_seed=vocab_seed)

        # Priority: chain-restored vocabulary beats the static seed. The seed is
        # the first-iteration bootstrap; once any iteration has run, the latest
        # committed runtime_vocab is the source of truth.
        if restored_runtime_vocab:
            state.current_runtime_vocab = list(restored_runtime_vocab)

        # Defensive copy: the workflow mutates this dict in place at iteration
        # end and must not alias the caller's reference.
        state.model_knowledge_cache = dict(restored_model_knowledge_cache or {})

        state.previous_proposal_data = restored_previous_proposal
        state.chain_formal_incumbent_reference = restored_chain_incumbent_score
        state.current_collapse_fingerprint_history = dict(
            restored_collapse_fingerprint_history or {}
        )
        state.current_prediction_memory = restored_prediction_memory or PredictionMemory()
        if all_model_types is not None:
            state.all_model_types = list(all_model_types)
        if recent_tune_outputs is not None:
            state.recent_tune_outputs = recent_tune_outputs
        return state

    # --- narrow mutation helpers ---------------------------------------------
    # Only two exist, and each encodes a RULE rather than an assignment. Adding
    # a setter per field would be ceremony, not ownership.

    def record_tune_output(self, output: Any) -> None:
        """Append a completed iteration's tuner output.

        Two collections advance together, and the deque's ``maxlen`` is what
        bounds the proposer's aggregate window — a caller appending to only one
        of them is the bug this method exists to make impossible.
        """
        self.iteration_results.append(output)
        self.recent_tune_outputs.append(output)


def chain_state_field_names() -> frozenset[str]:
    """The carrier's field names — the DERIVED forbidden set for the immutable
    carriers, and the surface the structural censuses check."""
    return frozenset(f.name for f in dataclass_fields(ChainState))
