"""
Unit tests for ``agent/prompt_templates/literature_review`` — the paper
compression prompt renderer. No I/O, no LLM, no network.

Covers Commit 3 of docs/commit_plan_ml_literature_review.md:
  - render_paper_extract_prompt determinism + content (snapshot-style asserts)
  - raw-text truncation at MAX_RAW_TEXT_CHARS
  - task-description injection (default + custom)
  - the "validation half" of the Commit 4 fallback: a valid dict from a mocked
    bridge.generate() parses into PaperExtract; a malformed payload raises.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from agent.prompt_templates.literature_review import (
    MAX_RAW_TEXT_CHARS,
    SIDERIUS_TASK,
    render_paper_extract_prompt,
    render_synthesis_prompt,
)
from agent.schemas.literature_review import PaperExtract

# The seven locked PaperExtract keys. Kept inline (not derived from the schema)
# so the test fails loudly if either the schema or the prompt drifts away from
# the agreed contract.
_EXPECTED_KEYS = (
    "title",
    "authors",
    "year",
    "core_idea",
    "architecture_details",
    "key_results",
    "relevance_to_task",
)


class TestRenderStructure:
    def test_returns_two_strings(self):
        system, user = render_paper_extract_prompt("some paper text")
        assert isinstance(system, str)
        assert isinstance(user, str)
        assert system and user

    def test_deterministic(self):
        a = render_paper_extract_prompt("identical input")
        b = render_paper_extract_prompt("identical input")
        assert a == b

    def test_system_prompt_lists_all_seven_keys(self):
        system, _ = render_paper_extract_prompt("text")
        for key in _EXPECTED_KEYS:
            assert key in system, f"system prompt missing key {key!r}"

    def test_system_prompt_has_anti_noise_and_math_rules(self):
        system, _ = render_paper_extract_prompt("text")
        # (cid:NN) glyph artifacts (F3) must be called out.
        assert "(cid:" in system
        # Math-in-prose / no-LaTeX instruction (F3).
        assert "LaTeX" in system
        # Despacing tolerance (run-together words).
        assert "missing spaces" in system

    def test_system_prompt_has_checkpoint_b_revision_instructions(self):
        # Checkpoint B revision: regime on every number + per-model mechanism
        # for benchmark papers.
        system, _ = render_paper_extract_prompt("text")
        assert "the training regime to EVERY performance number" in system
        assert "concrete mechanism" in system

    def test_system_prompt_has_generic_freq_split_rule(self):
        system, _ = render_paper_extract_prompt("text")
        # Generic, paper-conditional phrasing — keys off "if the paper reports".
        assert "frequency-split" in system
        assert "full-spectrum" in system
        # Must NOT name a specific paper (that would hallucinate for non-TIDMAD
        # papers compressed by the same prompt).
        assert "TIDMAD" not in system


class TestTaskInjection:
    def test_default_task_injected_and_placeholder_gone(self):
        system, _ = render_paper_extract_prompt("text")
        assert SIDERIUS_TASK in system
        assert "{TASK_DESCRIPTION}" not in system

    def test_custom_task_overrides_default(self):
        custom = "denoise audio recordings of whale song"
        system, _ = render_paper_extract_prompt("text", task_description=custom)
        assert custom in system
        assert SIDERIUS_TASK not in system
        assert "{TASK_DESCRIPTION}" not in system


class TestRawTextAndTruncation:
    def test_short_text_passed_verbatim(self):
        _, user = render_paper_extract_prompt("hello world body")
        assert "hello world body" in user
        assert "[...TRUNCATED...]" not in user

    def test_text_under_cap_not_truncated(self):
        body = "a" * (MAX_RAW_TEXT_CHARS - 10)
        _, user = render_paper_extract_prompt(body)
        assert "[...TRUNCATED...]" not in user
        assert body in user

    def test_text_over_cap_is_truncated(self):
        # 'Z' is absent from the user-prompt template + truncation marker, so
        # counting it isolates surviving body chars.
        body = "Z" * MAX_RAW_TEXT_CHARS + "UNIQUE_TAIL_SENTINEL"
        _, user = render_paper_extract_prompt(body)
        assert "[...TRUNCATED...]" in user
        # The portion past the cap must be dropped.
        assert "UNIQUE_TAIL_SENTINEL" not in user
        # Exactly MAX_RAW_TEXT_CHARS of the body survive (the marker is extra).
        assert user.count("Z") == MAX_RAW_TEXT_CHARS

    def test_text_at_cap_boundary_not_truncated(self):
        body = "b" * MAX_RAW_TEXT_CHARS
        _, user = render_paper_extract_prompt(body)
        assert "[...TRUNCATED...]" not in user


class TestPaperExtractValidationHalf:
    """The validation half of Commit 4's malformed-JSON fallback test.

    Commit 3 has no node yet, so we assert the contract directly: what
    ``bridge.generate()`` returns (a parsed dict) round-trips through
    ``PaperExtract.model_validate``; a structurally-invalid payload raises.
    A MagicMock stands in for the bridge so no API call happens.
    """

    def test_valid_generate_dict_parses(self):
        valid = {
            "title": "TIDMAD",
            "authors": "A. Author, B. Author",
            "year": "2024",
            "core_idea": "A time-series dataset and denoising benchmark.",
            "architecture_details": "WaveNet: dilated causal convs, full-spectrum.",
            "key_results": "WaveNet 4.99/5.16 under full-spectrum training.",
            "relevance_to_task": "Only full-spectrum baseline; directly comparable.",
        }
        bridge = MagicMock()
        bridge.generate.return_value = valid

        system, user = render_paper_extract_prompt("paper text")
        raw = bridge.generate(system, user)
        bridge.generate.assert_called_once_with(system, user)

        extract = PaperExtract.model_validate(raw)
        for key in _EXPECTED_KEYS:
            assert getattr(extract, key) == valid[key]

    def test_partial_dict_uses_empty_string_defaults(self):
        # The prompt tells the LLM to omit-or-empty unknown fields; a partial
        # dict must still validate, with "" defaults for the rest.
        extract = PaperExtract.model_validate({"title": "Only a title"})
        assert extract.title == "Only a title"
        assert extract.architecture_details == ""
        assert extract.relevance_to_task == ""

    def test_malformed_payload_raises(self):
        # A wrong-typed field (list where str is required) must raise rather
        # than silently coerce.
        bridge = MagicMock()
        bridge.generate.return_value = {"title": ["not", "a", "string"]}
        raw = bridge.generate(*render_paper_extract_prompt("text"))
        with pytest.raises(ValidationError):
            PaperExtract.model_validate(raw)

    def test_non_dict_payload_raises(self):
        with pytest.raises(ValidationError):
            PaperExtract.model_validate(["not", "a", "dict"])


class TestSynthesisPrompt:
    def _render(self):
        return render_synthesis_prompt(
            key_findings=["high-frequency band overfits"],
            bottlenecks=["loss saturates after ~5 epochs"],
            take_home_message="need more temporal depth",
            papers=[{"paper_id": "arxiv:1", "title": "P", "year": 2023, "summary": "s"}],
        )

    def test_returns_two_strings(self):
        system, user = self._render()
        assert isinstance(system, str) and isinstance(user, str)
        assert system and user

    def test_system_prompt_content_asserts(self):
        system, _ = self._render()
        # (a) bottleneck-grounding instruction
        assert "bottleneck" in system
        # (d) omission-over-weak-item rule
        assert "Omission beats a weak item" in system
        # (e) cite_id-matching instruction
        assert "cite_id" in system and "paper_id" in system
        # task-description injection
        assert SIDERIUS_TASK in system
        assert "{TASK_DESCRIPTION}" not in system

    def test_user_prompt_fronts_bottlenecks(self):
        _, user = self._render()
        assert "PRIMARY" in user
        assert "loss saturates after ~5 epochs" in user  # bottleneck present
        assert "arxiv:1" in user  # paper id available for cite_id matching
