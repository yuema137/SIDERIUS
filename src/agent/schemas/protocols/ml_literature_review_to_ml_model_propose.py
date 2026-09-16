# agent/schemas/protocols/ml_literature_review_to_ml_model_propose.py
"""
Edge protocols: ml-literature-review → ml-model-propose
(ml_literature_review → ml_model_proposal_agent)

Each function is a distinct protocol on this edge. Orchestrators choose
which protocol to apply at traversal time.

Protocol naming convention: {transport}_{data_scope}
  transport  : how data moves between nodes (local = in-memory, database = via DB)
  data_scope : what subset of the source output is transferred

Implemented
-----------
local_typed_evidence    Project one review into the Proposer-owned bounded
                        ``ProposerLiteratureReviewEvidence`` field. This is the
                        composed-workflow path.
local_all_channels      Legacy compatibility adapter for callers that still
                        use the generic four-channel external-agent surface.

Planned
-------
database_all_channels   DB-backed transfer: lit-review writes its output to the
                        database, the workflow reads it back and spreads it
                        into local_full_context. Requires a Postgres
                        StorageConfig backend. Raises NotImplementedError
                        until wired.

Design notes
------------
The workflow first constructs ``ProposalInput`` from Interpretation, then
attaches Literature and Data Analysis through separate target-owned typed
projections. The Proposer can therefore distinguish external claims from
observations measured on the run's own data. ``local_all_channels`` remains
only for backward-compatible independent callers; the composed workflow does
not unpack Literature Review through an untyped context dictionary.

Audit finding (Commit 5, no patch required):
  ``ml_result_interp_to_ml_model_propose.local_full_context`` at
  ``agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py:43-222``
  already accepts ``expert_context``, ``vocab_seed``, ``agent_cards``, and
  ``mindset`` as kwargs and maps each into ProposalInput. Lit-review's
  contribution flows in through that existing surface — this protocol
  produces the kwargs in the exact shape that protocol expects.

The cancelled ``reference_library`` channel (see the 2d revision in
``docs/commit_plan_ml_literature_review.md``) is deliberately absent: there
is no ``reference_library`` kwarg in the returned dict, and the lit-review
output carries no ``reference_library`` field. Equations reach the
proposer inline inside ``ExpertContextItem.content``, which travels
through ``expert_context``.
"""

from typing import Any

from agent.schemas.literature_review import LiteratureReviewOutput
from agent.schemas.proposal import ProposalInput
from agent.schemas.proposer_literature_evidence import (
    ProposerLiteratureAgentCard,
    ProposerLiteratureFinding,
    ProposerLiteratureReviewEvidence,
)


def _project(output: LiteratureReviewOutput) -> ProposerLiteratureReviewEvidence:
    return ProposerLiteratureReviewEvidence(
        run_name=output.run_name,
        agent_card=ProposerLiteratureAgentCard.model_validate(
            output.agent_card.model_dump(mode="python")
        ),
        findings=tuple(
            ProposerLiteratureFinding(
                source_ref=item.source_ref,
                content=item.content,
                confidence=item.confidence,
            )
            for item in output.findings
        ),
        retrieved_paper_ids=tuple(item.paper_id for item in output.retrieved_papers),
        search_rounds_used=output.search_rounds_used,
    )


def local_typed_evidence(
    output: LiteratureReviewOutput,
    *,
    proposal_input: ProposalInput,
) -> ProposalInput:
    """Attach Literature Review through the Proposer-owned typed projection."""

    payload = proposal_input.model_dump(mode="python")
    payload["literature_review_evidence"] = _project(output)
    return ProposalInput.model_validate(payload)


def local_all_channels(output: LiteratureReviewOutput) -> dict[str, Any]:
    """
    Map LiteratureReviewOutput → the four external-agent kwargs of
    ``local_full_context``, in memory.

    Consumes from ml-literature-review (LiteratureReviewOutput, via the
    four-channel ExternalAgentOutput base):
      - agent_card           : the lit-review agent's self-description
      - findings             : list[ExpertContextItem] — soft findings,
                                including any equations/pseudocode that
                                travel inline inside ``content`` (per the
                                2d synthesis-prompt revision).
      - new_vocab_candidates : list[VocabEntry] — empty in v1 (the lit-review
                                node does not populate this channel yet;
                                kept on the base schema for symmetry).
      - suggested_mindset    : str | None — empty in v1 (same rationale).

    NOT consumed (audit-trail only, never crosses the edge):
      - retrieved_papers     : every paper looked at this run, kept on the
                                output for inspection but not part of the
                                proposer's input.
      - search_rounds_used / run_name / started_at / finished_at :
                                run bookkeeping, audit-trail only.

    Returns (the four kwargs that ``local_full_context`` exposes for
    external-agent contribution; spread into it via ``**channels``):
      - expert_context  = output.findings
      - vocab_seed      = output.new_vocab_candidates
      - agent_cards     = [output.agent_card]    (wrapped in a one-element
                                                  list because the upstream
                                                  protocol's parameter is
                                                  ``list[AgentCard] | None``)
      - mindset         = output.suggested_mindset

    The return type is ``dict[str, Any]`` (not a typed schema object)
    because the consumer's calling convention is
    ``local_full_context(interp_output, storage, **channels)`` — the dict
    is unpacked into kwargs at the call site, not validated as a standalone
    object.

    There is **no** ``reference_library`` / ``reference_library_md`` entry
    in the returned dict. That channel was cancelled in the 2d revision;
    equations travel inline inside ``ExpertContextItem.content``.
    """
    return {
        "expert_context": list(output.findings),
        "vocab_seed": list(output.new_vocab_candidates),
        "agent_cards": [output.agent_card],
        "mindset": output.suggested_mindset,
    }


def database_all_channels(output: LiteratureReviewOutput) -> dict[str, Any]:
    """
    Database-backed protocol — reads the lit-review record from the database
    and returns the same four-kwarg dict as ``local_all_channels``. Raises
    NotImplementedError until a Postgres StorageConfig backend is wired.
    """
    raise NotImplementedError(
        "database_all_channels is not yet implemented. Wire a Postgres StorageConfig backend first."
    )
