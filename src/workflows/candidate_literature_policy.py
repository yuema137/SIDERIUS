"""Explicit candidate-graph restrictions; native workflow defaults stay unchanged."""

from agent.schemas.literature_review import LiteratureReviewInput


def require_candidate_literature_policy(value: LiteratureReviewInput, *, network: bool) -> None:
    """Refuse uncaptured local papers and retrieval without explicit network access."""
    if any(source.source_type == "local" for source in value.root_papers):
        raise ValueError(
            "native literature graph does not admit local papers; use the existing native "
            "literature workflow/CLI for checkout-relative local sources"
        )
    if not network and (value.root_papers or value.dynamic_search.enabled):
        raise ValueError("literature retrieval requires explicit network=true")
