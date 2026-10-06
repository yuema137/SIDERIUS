"""Validate vocabulary where its producing stage can still correct it.

Keep accepted raw values intact: the final ProposalOutput remains the conversion
boundary. The adapters below borrow its field types, not a parallel contract.
"""

from dataclasses import dataclass
from typing import Any

from pydantic import TypeAdapter, ValidationError

from agent.llm_bridge import LLMBridge
from agent.schemas.proposal import ProposalOutput

_LINKS = TypeAdapter(ProposalOutput.model_fields["proposed_vocab_links"].annotation)
_CANDIDATES = TypeAdapter(ProposalOutput.model_fields["proposed_vocab_candidates"].annotation)
_DISCOVERIES = TypeAdapter(ProposalOutput.model_fields["proposed_discoveries"].annotation)


class StageVocabularyError(ValueError):
    """A consumed vocabulary field must be corrected by its producing stage."""


@dataclass
class StageVocabulary:
    """Raw selected values; validation must not rewrite downstream prompt inputs."""

    links: Any
    candidates: list[dict]
    discoveries: list[dict]


def _validate(adapter: TypeAdapter, value: Any, path: str) -> None:
    try:
        adapter.validate_python(value)
    except ValidationError as exc:
        details = "; ".join(
            f"{' → '.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()[:5]
        )
        raise StageVocabularyError(f"{path}: {details}") from exc


def stage_vocabulary(raw: Any, *, stage: str) -> StageVocabulary:
    """Select and validate exactly the vocabulary consumed from this stage.

    Preserve legacy ignoring of non-dict entries and unconsumed kinds. Invalid
    consumed content is never silently dropped or repaired by another stage.
    """
    source = raw if isinstance(raw, dict) else {}
    links = source.get("proposed_vocab_links", []) if stage == "comparison" else []
    _validate(_LINKS, links, f"{stage}.proposed_vocab_links")
    candidates: list[dict] = []
    discoveries: list[dict] = []
    entries = source.get("proposed_vocab_candidates", [])
    try:
        iterator = iter(entries)
    except TypeError as exc:
        raise StageVocabularyError(
            f"{stage}.proposed_vocab_candidates: expected an iterable"
        ) from exc
    for index, candidate in enumerate(iterator):
        if not isinstance(candidate, dict):
            continue
        path = f"{stage}.proposed_vocab_candidates[{index}]"
        kind = candidate.get("kind", "")
        try:
            is_candidate = kind in {"feature", "capability"}
        except TypeError as exc:
            raise StageVocabularyError(f"{path}.kind: expected a hashable kind") from exc
        if is_candidate:
            _validate(_CANDIDATES, [candidate], path)
            candidates.append(candidate)
        elif kind == "discovery":
            _validate(_DISCOVERIES, [candidate], path)
            discoveries.append(candidate)
    return StageVocabulary(links, candidates, discoveries)


def correct_comparison_vocabulary(
    raw: Any,
    *,
    bridge: LLMBridge,
    system_prompt: str,
    user_prompt: str,
    components: Any,
    max_retries: int,
) -> Any:
    """Bounded repair before the comparison output reaches downstream stages."""
    import json

    for attempt in range(max_retries + 1):
        try:
            stage_vocabulary(raw, stage="comparison")
            return raw
        except StageVocabularyError as exc:
            if attempt == max_retries:
                raise RuntimeError(
                    f"Comparison stage vocabulary failed after {max_retries} correction retries. "
                    f"Last error: {exc}"
                ) from exc
            correction = (
                user_prompt
                + "\n\n## VALIDATION ERROR — CORRECT AND RESEND\n"
                + f"Your previous comparison response failed vocabulary validation:\n{exc}\n"
                + "Previous response:\n"
                + json.dumps(raw, ensure_ascii=False)
                + "\nReturn the FULL corrected JSON object (same output schema as instructed above), "
                + "fixing ONLY the invalid fields and keeping every other field unchanged."
            )
            raw = bridge.generate(
                system_prompt,
                correction,
                label="proposer.comparison.correction",
                components=components,
            )
    raise AssertionError("Comparison correction loop did not terminate")
